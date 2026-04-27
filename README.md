# chongming

[TOC]

作者: chakcy

版本: 0.1.0

## 运行项目

uv 环境

```shell
uv run serve
```

纯 python 环境

```shell
python -m venv .venv
source .venv/bin/activate # windwows 命令为 .venv\Scripts\activate
pip install  -r requirements.txt
pip install -e .
serve
```

## 打包项目

uv 环境

```shell
uv run build
``` 

纯 python 环境
```shell
source .venv/bin/activate # windwows 命令为 .venv\Scripts\activate
build
```

打包出来的文件在 build 目录下

```text
build
├── resources
│   ├── chongming.ico
│   ├── plugins.mbank
│   └── app.mbank
├── config.toml
├── db.sqlite3
└── chongming # windows chongming.exe
```

运行打包后的项目
```shell
cd build
chongming # windows chongming.exe
```

## docker镜像

打包镜像
```shell
docker build -t chongming:latest .
```

导出镜像
```shell
docker save -o chongming_latest.tar chongming:latest
```

导入镜像
```shell
docker load -i chongming_latest.tar
```

运行镜像
```shell
sudo chmod 777 ./deploy.sh
./deploy.sh
```
