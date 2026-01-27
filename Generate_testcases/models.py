from django.db import models
from django.conf import settings


class FeatureLevel1(models.Model):
    name = models.CharField(max_length=128, unique=True)  # 一级功能名
    code = models.CharField(max_length=64, blank=True, null=True, db_index=True)  # 可选：编码/业务Key
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class FeatureLevel2(models.Model):
    level1 = models.ForeignKey(FeatureLevel1, on_delete=models.CASCADE, related_name="level2_list")
    name = models.CharField(max_length=128)  # 二级功能名
    code = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    prompt = models.TextField(blank=True, null=True, help_text="场景提示词：该二级功能（场景）的提示词")  # 场景级别的提示词
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("level1", "name")]
        indexes = [
            models.Index(fields=["level1", "name"]),
        ]

    def __str__(self):
        return f"{self.level1.name} / {self.name}"


class TestCaseSeed(models.Model):
    """
    原始表：一级功能/二级功能/测试用例例子（种子样例）
    一个二级功能可以有多条种子样例（更利于泛化质量）
    """
    level2 = models.ForeignKey(FeatureLevel2, on_delete=models.CASCADE, related_name="seeds")
    text = models.TextField()  # 测试用例例子（如 Input）
    lang = models.CharField(max_length=16, default="zh")  # 可选：zh/en...
    source = models.CharField(max_length=32, default="import")  # import/manual 等
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["level2", "lang"]),
        ]


class GenerationSession(models.Model):
    """
    一次"生成会话/版本"
    - 用户输入 prompt，模型基于 level2 的 seed 泛化生成 N 条（通常 N=5）
    - 用户改 prompt 再生成 -> 新 session
    """
    level2 = models.ForeignKey(FeatureLevel2, on_delete=models.CASCADE, related_name="gen_sessions")
    # 移除单个seed关联，改为通过GenerationSeedConfig关联多个seed
    prompt = models.TextField(blank=True, null=True, help_text="可选：会话级别的提示词（会覆盖场景提示词）")  # 可选：会话级别的提示词
    model_name = models.CharField(max_length=128, blank=True, null=True)  # gpt-4o / xxx
    temperature = models.FloatField(default=0.7)
    top_p = models.FloatField(default=1.0)
    status = models.CharField(
        max_length=16,
        choices=[("draft", "draft"), ("done", "done"), ("failed", "failed")],
        default="draft",
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["level2", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    @property
    def effective_prompt(self):
        """获取有效提示词：优先使用会话级别的，否则使用场景级别的（二级功能的prompt）"""
        if self.prompt:
            return self.prompt
        return self.level2.prompt or ""


class GenerationSeedConfig(models.Model):
    """
    生成会话中的种子配置
    一个会话可以包含多个种子，每个种子可以指定生成数量
    """
    session = models.ForeignKey(GenerationSession, on_delete=models.CASCADE, related_name="seed_configs")
    seed = models.ForeignKey(TestCaseSeed, on_delete=models.CASCADE, related_name="gen_configs")
    n = models.PositiveSmallIntegerField(default=5, help_text="该种子要生成的用例数量")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("session", "seed")]
        indexes = [
            models.Index(fields=["session", "seed"]),
        ]

    def __str__(self):
        return f"{self.session} - {self.seed} (n={self.n})"


class GenerationItem(models.Model):
    """
    会话下的单条生成结果（临时工作区）
    支持：
    - 用户编辑（edited_text）
    - 单条重新生成（regen_from_item / regen_prompt）
    
    功能流程：
    1. 首次生成：存放到此表
    2. 修改/重新生成：更新此表的记录
    3. 最终满意后：点击"保存泛化测试用例"按钮，复制到SavedCaseItem表
    """
    session = models.ForeignKey(GenerationSession, on_delete=models.CASCADE, related_name="items")
    seed = models.ForeignKey(TestCaseSeed, on_delete=models.SET_NULL, null=True, blank=True, related_name="generated_items", help_text="该生成项来自哪个种子")
    idx = models.PositiveSmallIntegerField()  # 0~N，保证顺序
    raw_text = models.TextField()  # 模型原始输出
    edited_text = models.TextField(blank=True, null=True)  # 用户最终编辑稿（可为空）
    is_edited = models.BooleanField(default=False, db_index=True)

    # 单条重生成追溯（可选）
    regen_prompt = models.TextField(blank=True, null=True)
    regen_from_item = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="regen_children"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "idx"]),
            models.Index(fields=["is_edited"]),
            models.Index(fields=["seed"]),
        ]

    @property
    def final_text(self):
        return self.edited_text if self.is_edited and self.edited_text else self.raw_text


class SavedCaseItem(models.Model):
    """
    最终保存的测试用例（正式交付物）
    
    设计说明：
    - 简化设计：去掉 SavedCaseSet，直接在此表存储所有信息
    - 与GenerationItem区分：GenerationItem是临时工作区，SavedCaseItem是最终确认版本
    - 通过 saved_batch_id 字段将同一批保存的用例分组
    
    使用流程：
    - 用户在GenerationItem中修改/重新生成测试用例
    - 满意后点击"保存泛化测试用例"按钮
    - 系统将GenerationItem复制到此表，并生成唯一的saved_batch_id
    """
    # 关联字段
    level2 = models.ForeignKey(FeatureLevel2, on_delete=models.CASCADE, related_name="saved_items", help_text="所属场景")
    from_session = models.ForeignKey(GenerationSession, on_delete=models.SET_NULL, null=True, blank=True, help_text="来源会话，用于追溯")
    from_gen_item = models.ForeignKey(GenerationItem, on_delete=models.SET_NULL, null=True, blank=True, help_text="来源生成项，用于追溯")
    
    # 分组字段：用于标识哪些用例是同一批保存的
    saved_batch_id = models.CharField(max_length=64, db_index=True, help_text="保存批次ID，格式：level2_{id}_timestamp")
    
    # 用例内容
    idx = models.PositiveSmallIntegerField(help_text="在该批次中的序号")
    text = models.TextField(help_text="测试用例内容")
    
    # 版本管理字段
    version_title = models.CharField(max_length=256, blank=True, null=True, help_text="版本名称/备注")
    status = models.CharField(
        max_length=16,
        choices=[
            ("draft", "草稿"),
            ("confirmed", "已确认"),
            ("delivered", "已交付"),
        ],
        default="confirmed",
        db_index=True,
        help_text="用例状态"
    )
    
    # 创建信息
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("saved_batch_id", "idx")]
        indexes = [
            models.Index(fields=["level2", "created_at"]),
            models.Index(fields=["saved_batch_id", "idx"]),
            models.Index(fields=["status", "created_at"]),
        ]
    
    def __str__(self):
        return f"{self.level2.name} - 批次{self.saved_batch_id} - #{self.idx}"
