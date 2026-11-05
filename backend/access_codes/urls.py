from django.urls import path
from . import views

app_name = 'access_codes'

urlpatterns = [
    path('register/', views.register_user, name='register_user'),
    path('generate-professor/', views.generate_professor_access_code, name='generate_professor_access_code'),
    path('redeem/', views.redeem_access_code, name='redeem_access_code'),
    path('my-list/', views.list_user_access_codes, name='list_user_access_codes'),
    
    # Bot access code endpoints
    path('bot-groups/<int:bot_group_id>/bots/<int:bot_id>/generate/', views.generate_bot_access_code, name='generate_bot_access_code'),
    path('bot-groups/<int:bot_group_id>/bots/<int:bot_id>/', views.get_bot_access_code, name='get_bot_access_code'),
    path('bot-groups/<int:bot_group_id>/bots/<int:bot_id>/delete/', views.delete_bot_access_code, name='delete_bot_access_code'),

    path('bot-groups/<int:bot_group_id>/bots/<int:bot_id>/users/', views.get_bot_access_users, name='get_bot_access_users'),
    path('bot-groups/<int:bot_group_id>/bots/<int:bot_id>/users/<int:user_id>/remove/', views.remove_user_bot_access, name='remove_user_bot_access'),
]