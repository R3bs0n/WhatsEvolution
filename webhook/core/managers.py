from django.db import models


class TenantQuerySet(models.QuerySet):
    def for_empresa(self, empresa):
        if empresa is None:
            return self.none()
        return self.filter(empresa=empresa)


class TenantManager(models.Manager):
    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)

    def for_empresa(self, empresa):
        return self.get_queryset().for_empresa(empresa)
