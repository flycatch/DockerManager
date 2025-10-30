import os
from logger import log
from managers.docker_manager import DockerManager

if __name__ == "__main__":
    # Clear or create log.txt on start
    open('log.txt', 'w').close()
    DockerManager().run()