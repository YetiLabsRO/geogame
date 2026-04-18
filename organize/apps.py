from django.apps import AppConfig


class OrganizeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'organize'

    def ready(self):
        from organize import signals  # noqa: F401
