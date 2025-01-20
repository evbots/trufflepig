### Commands

docker build -t trufflepig .
docker run --rm --privileged -d -v $(pwd):/app --name trufflepig-container trufflepig
docker ps
docker exec trufflepig-container sudo -E pytest -v
docker exec -it trufflepig-container /bin/sh