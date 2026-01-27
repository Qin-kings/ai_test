from django.core.management.base import BaseCommand
from django.db import connection
from Generate_testcases.models import (
    FeatureLevel1, FeatureLevel2, TestCaseSeed,
    GenerationSession, GenerationItem, GenerationSeedConfig,
    SavedCaseItem
)


class Command(BaseCommand):
    help = '重排所有表的ID，使其连续（不删除数据）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='仅显示将要执行的操作，不实际修改数据',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN 模式 - 不会实际修改数据'))
        else:
            confirm = input('此操作将重排所有ID！是否继续？(yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.WARNING('操作已取消'))
                return

        self.stdout.write('开始重排ID...\n')

        # 按依赖顺序处理（先处理被依赖的表）
        models_to_reorder = [
            ('FeatureLevel1', FeatureLevel1),
            ('FeatureLevel2', FeatureLevel2),
            ('TestCaseSeed', TestCaseSeed),
            ('GenerationSession', GenerationSession),
            ('GenerationSeedConfig', GenerationSeedConfig),
            ('GenerationItem', GenerationItem),
            ('SavedCaseItem', SavedCaseItem),
        ]

        for model_name, model in models_to_reorder:
            result = self._reorder_model_ids(model, model_name, dry_run)
            if result:
                self.stdout.write(f'  {result}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN 完成 - 未实际修改数据'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ ID重排完成！'))

    def _reorder_model_ids(self, model, model_name, dry_run=False):
        """重排单个模型的ID，并同步更新所有外键"""
        items = list(model.objects.all().order_by('id'))
        
        if not items:
            return f'✓ {model_name}: 无数据，跳过'
        
        # 建立ID映射表 {旧ID: 新ID}
        id_mapping = {}
        needs_reorder = False
        for idx, item in enumerate(items, start=1):
            id_mapping[item.id] = idx
            if item.id != idx:
                needs_reorder = True
        
        if not needs_reorder:
            return f'✓ {model_name}: ID已连续，无需重排 (1-{len(items)})'
        
        if dry_run:
            old_ids = [item.id for item in items]
            new_ids = list(range(1, len(items) + 1))
            return f'⚠ {model_name}: 将重排 {len(items)} 条记录\n    旧ID: {old_ids}\n    新ID: {new_ids}'
        
        # 实际执行重排
        table_name = model._meta.db_table
        
        with connection.cursor() as cursor:
            # 临时禁用外键检查
            cursor.execute('SET FOREIGN_KEY_CHECKS=0')
            
            try:
                # 🔧 修复：先同步外键到负数，BEFORE更新主表
                # 这样可以确保在更新主表ID之前，外键已经跟随变化
                self._update_foreign_keys_to_negative(model_name, id_mapping, cursor)
                
                # 1. 将主表所有ID设为负数（避免冲突）
                for old_id in id_mapping.keys():
                    cursor.execute(f"UPDATE {table_name} SET id = -{old_id} WHERE id = {old_id}")
                
                # 2. 重新分配正数ID（主表）
                for old_id, new_id in id_mapping.items():
                    cursor.execute(f"UPDATE {table_name} SET id = {new_id} WHERE id = -{old_id}")
                
                # 3. 同步外键到正数（与主表新ID对应）
                self._update_foreign_keys_to_positive(model_name, id_mapping, cursor)
                
                # 4. 重置AUTO_INCREMENT
                next_id = len(items) + 1
                cursor.execute(f"ALTER TABLE {table_name} AUTO_INCREMENT = {next_id}")
                
            finally:
                # 重新启用外键检查
                cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        
        return f'✓ {model_name}: 已重排 {len(items)} 条记录 (1-{len(items)}，下一个ID: {len(items)+1})'
    
    def _update_foreign_keys_to_negative(self, model_name, id_mapping, cursor):
        """第一步：将所有外键改为负数（在主表ID改变之前）"""
        
        # 定义外键关系映射：{模型名: [(子表名, 外键列名)]}
        fk_updates = {
            'FeatureLevel1': [
                ('generate_testcases_featurelevel2', 'level1_id'),
            ],
            'FeatureLevel2': [
                ('generate_testcases_testcaseseed', 'level2_id'),
                ('generate_testcases_generationsession', 'level2_id'),
                ('generate_testcases_savedcaseitem', 'level2_id'),
            ],
            'TestCaseSeed': [
                ('generate_testcases_generationseedconfig', 'seed_id'),
                ('generate_testcases_generationitem', 'seed_id'),
            ],
            'GenerationSession': [
                ('generate_testcases_generationseedconfig', 'session_id'),
                ('generate_testcases_generationitem', 'session_id'),
                ('generate_testcases_savedcaseitem', 'from_session_id'),
            ],
            'GenerationItem': [
                ('generate_testcases_generationitem', 'regen_from_item_id'),
                ('generate_testcases_savedcaseitem', 'from_gen_item_id'),
            ],
        }
        
        if model_name not in fk_updates:
            return
        
        # 关键：此时主表ID还是原始值，所以我们用原始ID来查找外键
        for table, fk_column in fk_updates[model_name]:
            for old_id in id_mapping.keys():
                # 将外键从旧ID改为负数
                cursor.execute(
                    f"UPDATE {table} SET {fk_column} = -{old_id} "
                    f"WHERE {fk_column} = {old_id}"
                )
    
    def _update_foreign_keys_to_positive(self, model_name, id_mapping, cursor):
        """第二步：将所有外键改为新的正数ID（在主表ID改变之后）"""
        
        # 定义外键关系映射：{模型名: [(子表名, 外键列名)]}
        fk_updates = {
            'FeatureLevel1': [
                ('generate_testcases_featurelevel2', 'level1_id'),
            ],
            'FeatureLevel2': [
                ('generate_testcases_testcaseseed', 'level2_id'),
                ('generate_testcases_generationsession', 'level2_id'),
                ('generate_testcases_savedcaseitem', 'level2_id'),
            ],
            'TestCaseSeed': [
                ('generate_testcases_generationseedconfig', 'seed_id'),
                ('generate_testcases_generationitem', 'seed_id'),
            ],
            'GenerationSession': [
                ('generate_testcases_generationseedconfig', 'session_id'),
                ('generate_testcases_generationitem', 'session_id'),
                ('generate_testcases_savedcaseitem', 'from_session_id'),
            ],
            'GenerationItem': [
                ('generate_testcases_generationitem', 'regen_from_item_id'),
                ('generate_testcases_savedcaseitem', 'from_gen_item_id'),
            ],
        }
        
        if model_name not in fk_updates:
            return
        
        # 此时主表ID已经是新ID，外键是负数，我们将负数改为新ID
        for table, fk_column in fk_updates[model_name]:
            for old_id, new_id in id_mapping.items():
                # 将外键从负数改为新ID
                cursor.execute(
                    f"UPDATE {table} SET {fk_column} = {new_id} "
                    f"WHERE {fk_column} = -{old_id}"
                )
