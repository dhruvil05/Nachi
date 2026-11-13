from nachi.agents.grader.agent import build
from nachi.core.serve import main

if __name__ == "__main__":
    main(build, "grader")
