# Generate_testcases/llm_client.py
import os
import re
from typing import List
from zhipuai import ZhipuAI


class LLMError(RuntimeError):
    """LLM 调用或返回内容不符合预期时抛出。"""
    pass


def safe_print(s: str) -> None:
    """
    Windows 控制台常见：gbk 不能打印 emoji/部分字符，导致 UnicodeEncodeError。
    用 replace 兜底，避免后端 500。
    """
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("gbk", errors="replace").decode("gbk", errors="replace"))


def _split_lines(text: str) -> List[str]:
    """
    将模型输出切成“每行一条用例”，并清理常见列表前缀：
    - 1. / 1) / - / *
    """
    lines: List[str] = []
    if not text:
        return lines

    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        s = re.sub(r"^\s*(\d+[\.\)]|[-*])\s*", "", s).strip()
        if s:
            lines.append(s)
    return lines


def _split_blocks(text: str) -> List[str]:
    """
    将模型输出切成“按空行分隔的块”，每个块代表一条用例（可以是多行对话）。
    修复：代码块 ``` ... ``` 内部的空行不应被当作用例分隔。
    """
    if not text:
        return []

    blocks: List[str] = []
    buf: List[str] = []
    in_code_fence = False  # 是否在 ``` 代码块里

    for raw in text.splitlines():
        line = raw.rstrip("\r\n")

        # 进入/退出代码块
        if line.strip().startswith("```"):
            in_code_fence = not in_code_fence
            buf.append(line)
            continue

        # 只有在“非代码块模式”下，空行才代表一个用例结束
        if (not in_code_fence) and (line.strip() == ""):
            if buf:
                block = "\n".join(buf).strip()
                if block:
                    blocks.append(block)
                buf = []
            continue

        buf.append(line)

    if buf:
        block = "\n".join(buf).strip()
        if block:
            blocks.append(block)

    # 去掉常见编号前缀（只对块首行做一次）
    cleaned: List[str] = []
    for b in blocks:
        lines = b.splitlines()
        if not lines:
            continue
        first = re.sub(r"^\s*(\d+[\.\)]|[-*])\s*", "", lines[0]).rstrip()
        rest = lines[1:]
        nb = "\n".join([first] + rest).strip()
        if nb:
            cleaned.append(nb)
    return cleaned


def _is_dialog_seed(seed_text: str) -> bool:
    """
    判定种子是否为“对话”：
    - 包含换行
    - 或出现 A:/B: / 用户:/助手: / Q:/A: 等常见标记
    """
    s = (seed_text or "").strip()
    if "\n" in s:
        return True
    # 常见对话格式标记
    if re.search(r"(?mi)^\s*(A|B|用户|助手|Q|A)\s*[:：]", s):
        return True
    return False


# 固定系统提示词：面向“翻译软件”测试用例生成
SYSTEM_PROMPT = (
    "你是资深软件测试工程师，专门为【翻译软件】设计测试用例。"
    "任务：根据给定的【种子测试用例】泛化生成更多可执行的测试用例。"
    "如果【种子测试用例】是对话形式，那么每条泛化用例也必须是一个完整对话（可多行），"
    "并且【不同用例之间必须用一个空行分隔】。"
    "输出要求：必须中文；不要编号；不要解释；不要输出多余内容。"
)

# 通用硬要求（尽量精炼，但覆盖你想要的关键维度）
BASE_REQUIREMENTS = (
    "请基于种子用例进行泛化，不要简单复述种子。"
    "覆盖尽量多的测试维度：语种方向/多语混合；长短句/段落/列表/换行；"
    "数字/日期时间/货币/单位；专有名词/人名地名/缩写；"
    "特殊字符与格式：emoji、引号括号、#@%、URL、邮箱、代码片段；"
    "边界与异常：空输入、超长、重复字符、前后空格、乱码/编码问题。"
    "质量检查点包括：不丢失信息、不新增信息、数字/日期不被改写、专名不乱翻、格式尽量保持、术语一致。"
)


def generate_cases_for_seed(
    *,
    level1_name: str,
    level2_name: str,
    seed_text: str,
    prompt: str,
    n: int,
    temperature: float,
    top_p: float,
    idx
) -> List[str]:
    """
    输入：
      - level1_name: 一级功能
      - level2_name: 二级功能/场景名称
      - seed_text: 种子测试用例（可以是一句话，也可以是对话多行）
      - prompt: 场景提示词（可为空）
      - n: 生成条数
      - temperature/top_p: 采样参数

    输出：
      - List[str]：长度为 n（尽力保证）
        * 非对话：每个元素是一条用例（一行）
        * 对话：每个元素是一个完整对话块（可多行，含换行）
    """
    api_key = os.getenv("ZHIPU_API_KEY", "")
    model = os.getenv("ZHIPU_MODEL", "glm-4")

    if not api_key:
        raise LLMError("缺少环境变量 ZHIPU_API_KEY")

    if not (level2_name or "").strip():
        raise LLMError("缺少二级功能名称 level2_name")

    if not (seed_text or "").strip():
        raise LLMError("缺少种子用例 seed_text")

    if n <= 0:
        return []

    client = ZhipuAI(api_key=api_key)

    # 场景提示词可选：前端可填可不填
    extra = (prompt or "").strip()
    extra_block = ""
    if extra:
        extra_block = (
            "\n【场景补充提示（若与通用要求冲突，请优先满足本段中的业务重点，但输出格式仍必须遵守）】\n"
            f"{extra}\n"
        )

    is_dialog = _is_dialog_seed(seed_text)

    # 对话输出规则：必须用空行分隔每条用例（每条用例可以多行）
    dialog_format_rule = ""
    if is_dialog:
        dialog_format_rule = (
            "\n【对话格式要求】\n"
            "1) 每条用例必须是一个完整对话（可多行）。\n"
            "2) 不同用例之间必须用一个空行分隔。\n"
            "3) 对话行可以使用“用户：/助手：”或“A：/B：”等标记。\n"
        )

    user = (
        f"【一级功能】{level1_name}\n"
        f"【二级功能（具体场景）】{level2_name}\n"
        f"{extra_block}\n"
        f"【种子测试用例】\n{seed_text}\n\n"
        f"请生成 {n} 条新的【泛化测试用例】。\n"
        f"具体要求：{BASE_REQUIREMENTS}\n"
        f"{dialog_format_rule}\n"
        "再次强调：必须中文；不要编号；不要解释；不要输出多余内容。"
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=float(temperature),
            top_p=float(top_p),
        )
    except Exception as e:
        raise LLMError(f"智谱调用失败：{e}")

    content = (resp.choices[0].message.content or "").strip()

    print(f"===== ZHIPU LLM RAW OUTPUT{idx} (FIRST RESPONSE) =====")
    safe_print(content)
    print("===== END RAW OUTPUT =====\n")

    # 解析策略：对话用“块”，非对话用“行”
    if is_dialog:
        blocks = _split_blocks(content)
        # 兜底：如果模型没按空行分隔导致 blocks 太少，就退回按行拆（至少保证有输出）
        if len(blocks) >= 1:
            lines = blocks
        else:
            lines = _split_lines(content)
    else:
        lines = _split_lines(content)

    # 尽力返回 n 条（保持你现有前后端/DB流程稳定）
    if len(lines) < n:
        if lines:
            filler = lines[-1]
            lines = lines + [filler] * (n - len(lines))
        else:
            raise LLMError("模型未返回可解析的用例内容，请重试。")

    return lines[:n]
