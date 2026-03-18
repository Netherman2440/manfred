from dependency_injector import containers, providers
from config import Settings

class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=[]
    )

    settings: providers.Singleton[Settings] = providers.Singleton(Settings)