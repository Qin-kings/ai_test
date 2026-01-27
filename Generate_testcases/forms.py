# app/forms.py
from django import forms
from .models import (
    GenerationSession, GenerationItem,
    FeatureLevel1, FeatureLevel2, TestCaseSeed, GenerationSeedConfig
)
from django.forms import modelformset_factory


class FeatureLevel1Form(forms.ModelForm):
    """一级功能表单：支持创建或选择"""
    level1_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    use_existing = forms.BooleanField(required=False, initial=False, widget=forms.CheckboxInput(attrs={'class': 'use-existing-checkbox'}))
    
    class Meta:
        model = FeatureLevel1
        fields = ["name", "code"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "输入一级功能名称", "class": "form-control"}),
            "code": forms.TextInput(attrs={"placeholder": "可选：编码/业务Key", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 为选择已存在的一级功能添加选择框
        self.fields['existing_level1'] = forms.ModelChoiceField(
            queryset=FeatureLevel1.objects.all().order_by('name'),
            required=False,
            widget=forms.Select(attrs={"class": "form-control"}),
            label="或选择已存在的一级功能"
        )


class FeatureLevel2Form(forms.ModelForm):
    """二级功能表单：支持创建或选择"""
    level2_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    use_existing = forms.BooleanField(required=False, initial=False, widget=forms.CheckboxInput(attrs={'class': 'use-existing-checkbox'}))
    
    class Meta:
        model = FeatureLevel2
        fields = ["name", "code", "prompt"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "输入二级功能名称", "class": "form-control"}),
            "code": forms.TextInput(attrs={"placeholder": "可选：编码", "class": "form-control"}),
            "prompt": forms.Textarea(attrs={"rows": 4, "placeholder": "场景提示词：该二级功能（场景）的提示词", "class": "form-control"}),
        }

    def __init__(self, *args, level1=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.level1 = level1
        # 为选择已存在的二级功能添加选择框
        if level1:
            self.fields['existing_level2'] = forms.ModelChoiceField(
                queryset=FeatureLevel2.objects.filter(level1=level1).order_by('name'),
                required=False,
                widget=forms.Select(attrs={"class": "form-control"}),
                label="或选择已存在的二级功能"
            )


class SeedSelectionForm(forms.Form):
    """种子选择表单：支持选择多个种子并指定每个种子的生成数量"""
    def __init__(self, *args, level2=None, **kwargs):
        super().__init__(*args, **kwargs)
        if level2:
            seeds = TestCaseSeed.objects.filter(level2=level2).order_by("-created_at")
            for seed in seeds:
                field_name = f"seed_{seed.id}"
                self.fields[field_name] = forms.BooleanField(
                    required=False,
                    label=f"选择种子",
                    widget=forms.CheckboxInput(attrs={'class': 'seed-checkbox'})
                )
                self.fields[f"{field_name}_n"] = forms.IntegerField(
                    required=False,
                    min_value=1,
                    max_value=50,
                    initial=5,
                    label="生成数量",
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control seed-n-input',
                        'style': 'width: 80px; display: inline-block;',
                        'disabled': True
                    })
                )
                # 存储seed对象供后续使用
                self.fields[field_name].seed = seed

    def get_selected_seeds(self):
        """获取选中的种子及其生成数量（需要在is_valid()之后调用）"""
        if not self.is_valid():
            return []
        
        selected = []
        for field_name, field in self.fields.items():
            if field_name.startswith('seed_') and not field_name.endswith('_n'):
                if self.cleaned_data.get(field_name, False):
                    n_field_name = f"{field_name}_n"
                    n = self.cleaned_data.get(n_field_name, 5) or 5
                    seed = getattr(field, 'seed', None)
                    if seed:
                        selected.append((seed, n))
        return selected


class GenerationSessionForm(forms.ModelForm):
    """生成会话表单：已简化为只包含模型参数"""
    class Meta:
        model = GenerationSession
        fields = ["prompt", "temperature", "top_p"]
        widgets = {
            "prompt": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "可选：会话级别的提示词（会覆盖场景提示词）",
                "class": "form-control"
            }),
            "temperature": forms.NumberInput(attrs={"step": 0.1, "class": "form-control"}),
            "top_p": forms.NumberInput(attrs={"step": 0.1, "class": "form-control"}),
        }


class GenerationItemEditForm(forms.ModelForm):
    """
    编辑单条用例：只让用户改 edited_text
    """
    class Meta:
        model = GenerationItem
        fields = ["edited_text"]
        widgets = {
            "edited_text": forms.Textarea(attrs={"rows": 3}),
        }


GenerationItemFormSet = forms.modelformset_factory(
    GenerationItem,
    form=GenerationItemEditForm,
    extra=0,
    can_delete=False,
)


class SaveCaseSetForm(forms.Form):
    """
    保存到最终库的表单：版本名称和状态
    注意：这不再关联SavedCaseSet模型，因为该模型已删除
    """
    title = forms.CharField(
        required=False,
        max_length=256,
        widget=forms.TextInput(attrs={
            "placeholder": "可选：版本名/备注",
            "class": "form-control"
        }),
        label="版本名称"
    )
    status = forms.ChoiceField(
        choices=[
            ("draft", "草稿"),
            ("confirmed", "已确认"),
            ("delivered", "已交付"),
        ],
        initial="confirmed",
        widget=forms.Select(attrs={"class": "form-control"}),
        label="状态"
    )


class TestCaseSeedForm(forms.ModelForm):
    """手动添加种子测试用例的表单"""
    class Meta:
        model = TestCaseSeed
        fields = ["text"]
        widgets = {
            "text": forms.Textarea(attrs={
                "placeholder": "输入测试用例内容...",
                "class": "form-control",
                "rows": 4,
                "style": "width: 100%;"
            })
        }
        labels = {
            "text": "测试用例内容"
        }
