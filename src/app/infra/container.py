from app.core.config import Settings
from dependency_injector import providers, containers

class Container(containers.DeclarativeContainer):
    config = providers.Configuration()

    settings: providers.Singleton[Settings] = providers.Singleton(
        Settings
    )

    #LLM

    #SLM

    #GRAPH BUILDER

    