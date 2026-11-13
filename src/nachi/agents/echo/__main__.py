from nachi.agents.echo.agent import EchoAgent
from nachi.core.serve import main

if __name__ == "__main__":
    main(lambda ctx: EchoAgent(), "echo")
