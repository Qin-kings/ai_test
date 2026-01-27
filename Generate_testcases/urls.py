from django.urls import path
from . import views
app_name = "Generate_testcases"

urlpatterns = [
    path("", views.testcase_workspace, name="testcase_workspace"),
    path("level2/", views.level2_list, name="level2_list"),
    path("level2/<int:level2_id>/", views.level2_detail, name="level2_detail"),
    path("session/<int:session_id>/edit/", views.session_edit_and_save, name="session_edit_and_save"),
    # 新功能：创建或选择场景
    path("create-scenario/", views.create_or_select_scenario, name="create_or_select_scenario"),
    # AJAX接口
    path("api/get-level2-list/", views.get_level2_list, name="get_level2_list"),
    path("api/get-seed-list/", views.get_seed_list, name="get_seed_list"),
    path("api/add-level1/", views.add_level1, name="add_level1"),
    path("api/add-level2/", views.add_level2, name="add_level2"),
    path("api/add-seed/", views.add_seed, name="add_seed"),
    path("api/workspace-generate/", views.workspace_generate, name="workspace_generate"),
    path("api/delete-items/", views.delete_items, name="delete_items"),
    path("api/update-level1/", views.update_level1, name="update_level1"),
    path("api/update-level2/", views.update_level2, name="update_level2"),
    path("api/update-seed/", views.update_seed, name="update_seed"),
    path("api/regenerate-item/", views.regenerate_item, name="regenerate_item"),
    path("api/save-all-edits/", views.save_all_edits, name="save_all_edits"),
    path("api/save-to-final/", views.save_to_final, name="save_to_final"),
]