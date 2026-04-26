import core.config as config


async def init_system_config():
    override = config.system_config.get("ua_override")
    if override:
        config.OUTBOUND_USER_AGENT = override
    else:
        config.OUTBOUND_USER_AGENT = config.DEFAULT_OUTBOUND_USER_AGENT
