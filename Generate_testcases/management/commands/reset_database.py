from django.core.management.base import BaseCommand
from django.db import connection
from Generate_testcases.models import (
    FeatureLevel1, FeatureLevel2, TestCaseSeed,
    GenerationSession, GenerationItem, GenerationSeedConfig,
    SavedCaseItem
)


class Command(BaseCommand):
    help = '清空所有测试用例数据并重置自增ID'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='强制执行，不需要确认',
        )

    def handle(self, *args, **options):
        if not options['force']:
            confirm = input('此操作将删除所有数据！是否继续？(yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.WARNING('操作已取消'))
                return

        self.stdout.write('开始清空数据...')

        # 按依赖顺序删除（先删除子表，后删除父表）
        models_to_clear = [
            ('SavedCaseItem', SavedCaseItem),
            ('GenerationItem', GenerationItem),
            ('GenerationSeedConfig', GenerationSeedConfig),
            ('GenerationSession', GenerationSession),
            ('TestCaseSeed', TestCaseSeed),
            ('FeatureLevel2', FeatureLevel2),
            ('FeatureLevel1', FeatureLevel1),
        ]

        for model_name, model in models_to_clear:
            count = model.objects.count()
            model.objects.all().delete()
            self.stdout.write(f'  ✓ {model_name}: 删除 {count} 条记录')

        # 重置MySQL自增ID
        self.stdout.write('\n重置自增ID...')
        with connection.cursor() as cursor:
            tables = [
                'generate_testcases_savedcaseitem',
                'generate_testcases_generationitem',
                'generate_testcases_generationseedconfig',
                'generate_testcases_generationsession',
                'generate_testcases_testcaseseed',
                'generate_testcases_featurelevel2',
                'generate_testcases_featurelevel1',
            ]
            
            for table in tables:
                try:
                    cursor.execute(f"ALTER TABLE {table} AUTO_INCREMENT = 1")
                    self.stdout.write(f'  ✓ {table}: 自增ID已重置')
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  ✗ {table}: {str(e)}'))

        self.stdout.write(self.style.SUCCESS('\n✓ 数据库已清空并重置！'))
