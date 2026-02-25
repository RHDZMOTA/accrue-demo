import enum

from accrue.datatools.dao.service.interface import ServiceInterface
from accrue.datatools.dao.service._postgres import PostgresService
from accrue.datatools.dao.service._delta import DeltaService


class ServiceCatalog(enum.Enum):
    POSTGRES = PostgresService
    DELTA = DeltaService

    def auto(self, **kwargs) -> ServiceInterface:
        return self.value.auto(**kwargs)

    def __call__(self, **kwargs) -> ServiceInterface:
        return self.auto(**kwargs)
