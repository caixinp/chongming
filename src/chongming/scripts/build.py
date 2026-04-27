import os
import platform
import shutil
import subprocess
import sys
import asyncio
from pathlib import Path

from module_bank import PythonToSQLite
from module_bank.encryption import Encryption
from sqlite_vfs.core import SQLiteVFS
from sqlite_vfs.folder_packer import FolderPacker


is_windows = platform.system() == "Windows"


def build_vue_web():
    """
    打包 Vue Web 前端项目

    该函数执行以下操作:
    1. 运行 npm build 命令构建 Vue 项目
    2. 将构建产物打包到 SQLite VFS 虚拟文件系统中

    Returns:
        None: 无返回值,通过打印信息反馈执行结果
    """
    # 构建 Vue Web 命令
    dist_dir = "./src/chongming-web/dist"
    output_db = "./build/static.svfs"
    fs_name = "frontend"
    cmd = [
        "npm",
        "run",
        "build",
    ]
    result = subprocess.run(
        cmd,
        cwd="./src/chongming-web",
        capture_output=True,
        text=True,
        shell=is_windows,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print("打包 Vue Web 失败")
        print("标准输出:", result.stdout)
        print("错误输出:", result.stderr)
        return
    else:
        print("Vue Web 打包成功")
        if result.stdout:
            print(result.stdout)

    # 检查 dist 目录是否存在
    if not os.path.exists(dist_dir):
        print(f"错误: dist 目录不存在: {dist_dir}")
        return

    vfs = SQLiteVFS(output_db, compress=False)
    packer = FolderPacker(
        sqlite_vfs=vfs,
        exclude_patterns=[],
        fs_name=fs_name,
    )

    try:
        packer.pack_folder(dist_dir)
        print(f"✅ 打包完成,文件保存为 {output_db}")
    finally:
        vfs.close()


def run_pyarmor_obfuscate():
    """
    使用 PyArmor 对关键 Python 文件进行代码混淆

    该函数遍历预定义的文件列表,对每个文件执行 pyarmor gen 命令进行混淆处理,
    以保护源代码不被轻易反编译。

    处理的文件包括:
    - main.py (主入口文件)
    - server.py (服务器文件)
    - utils/launch.py (启动工具)
    - utils/config.py (配置工具)

    Returns:
        None: 无返回值,遇到错误时提前返回
    """
    # pyarmor obfuscate --output=obfuscated_script.py original_script.py
    obfuscate_files = [
        ("main.py", "./"),
        ("server.py", "./"),
        ("utils/launch.py", "./utils"),
        ("utils/config.py", "./utils"),
    ]
    for file, output in obfuscate_files:
        cmd = [
            "pyarmor",
            "gen",
            f"--output={output}",
            file,
        ]
        result = subprocess.run(cmd, cwd="./build", capture_output=True, text=True)
        if result.returncode != 0:
            print(f"打包文件: {file} 失败")
            print(result.stderr)
            return
        else:
            print(result.stdout)
        print(f"打包文件: {file}")


def run_pyinstaller():
    """
    使用 PyInstaller 将应用打包成单文件可执行程序

    该函数根据操作系统平台(Windows/非Windows)构建不同的 PyInstaller 命令,
    包含所有必要的隐藏导入以确保依赖库被正确打包。

    Windows 和非 Windows 平台的主要区别:
    - 非 Windows 平台额外包含 gunicorn 相关模块

    Returns:
        None: 无返回值,通过打印信息反馈执行结果
    """
    try:
        # 构建 PyInstaller 命令
        if is_windows:
            cmd = [
                sys.executable,
                "-m",
                "PyInstaller",
                "--onefile",
                "--noconfirm",
                "--optimize",
                "2",
                "--strip",
                "--name",
                "chongming",
                "--distpath",
                ".",
                "--workpath",
                "./build_temp",
                "--specpath",
                "./specs",
                "--clean",
                # 隐藏导入
                "--hidden-import",
                "utils",
                "--hidden-import",
                "utils.launch",
                "--hidden-import",
                "utils.config",
                "--hidden-import",
                "server",
                "--hidden-import",
                "module_bank",
                "--hidden-import",
                "fastapi",
                "--hidden-import",
                "fastapi.staticfiles",
                "--hidden-import",
                "fastapi.middleware.cors",
                "--hidden-import",
                "uvicorn",
                "--hidden-import",
                "sqlmodel",
                "--hidden-import",
                "aiosqlite",
                "--hidden-import",
                "aiofiles",
                "--hidden-import",
                "apscheduler",
                "--hidden-import",
                "diskcache",
                "--hidden-import",
                "bcrypt",
                "--hidden-import",
                "sqlite_vfs",
                "--hidden-import",
                "python_multipart",
                "--hidden-import",
                "sqlite_vfs.core",
                "--hidden-import",
                "jwt",
                # 其他选项
                "--icon",
                "../../public/chongming.ico",
                "main.py",
            ]
        else:
            cmd = [
                sys.executable,
                "-m",
                "PyInstaller",
                "--onefile",
                "--noconfirm",
                "--optimize",
                "2",
                "--strip",
                "--name",
                "chongming",
                "--distpath",
                ".",
                "--workpath",
                "./build_temp",
                "--specpath",
                "./specs",
                "--clean",
                # 隐藏导入
                "--hidden-import",
                "utils",
                "--hidden-import",
                "utils.launch",
                "--hidden-import",
                "utils.config",
                "--hidden-import",
                "server",
                "--hidden-import",
                "module_bank",
                "--hidden-import",
                "fastapi",
                "--hidden-import",
                "fastapi.staticfiles",
                "--hidden-import",
                "fastapi.middleware.cors",
                "--hidden-import",
                "uvicorn",
                "--hidden-import",
                "sqlmodel",
                "--hidden-import",
                "aiosqlite",
                "--hidden-import",
                "aiofiles",
                "--hidden-import",
                "apscheduler",
                "--hidden-import",
                "diskcache",
                "--hidden-import",
                "bcrypt",
                "--hidden-import",
                "sqlite_vfs",
                "--hidden-import",
                "python_multipart",
                "--hidden-import",
                "sqlite_vfs.core",
                "--hidden-import",
                "jwt",
                # gunicorn
                "--hidden-import",
                "gunicorn.glogging",
                "--hidden-import",
                "gunicorn.app",
                "--hidden-import",
                "gunicorn.app.wsgiapp",
                # 其他选项
                "--icon",
                "../../public/chongming.ico",
                "main.py",
            ]

        print(f"正在运行 PyInstaller: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd="./build", capture_output=True, text=True)

        if result.returncode == 0:
            print("PyInstaller 打包成功!")
            print(result.stdout)
        else:
            print("PyInstaller 打包失败!")
            print("错误信息:", result.stderr)

    except FileNotFoundError:
        print("错误:未找到 PyInstaller,请先安装 PyInstaller:pip install pyinstaller")
    except Exception as e:
        print(f"PyInstaller 执行出错: {e}")


async def init_database():
    """
    异步初始化数据库

    该函数执行以下操作:
    1. 从配置中读取数据库连接信息
    2. 创建异步数据库引擎和会话工厂
    3. 设置 SQLite 优化参数(WAL 模式和同步策略)
    4. 创建所有 SQLModel 定义的数据库表
    5. 初始化权限系统和默认管理员账户

    Raises:
        ValueError: 当数据库配置不存在时抛出
        OperationalError: 当数据库操作出现异常时抛出(已存在表的情况除外)

    Returns:
        None: 无返回值
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..app.core.config import get_config
    from ..app.task.dev_init_db import init_permission, dev_init_admin

    database = get_config()["database"]
    database_type = database["type"]
    database_config = database.get(database_type, None)
    if database_config is None:
        raise ValueError("配置不存在")
    os.makedirs("./build/data", exist_ok=True)
    engine = create_async_engine(
        "sqlite+aiosqlite:///./build/data/database.db", **database_config
    )
    async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        if database_type == "sqlite":
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
        try:
            await conn.run_sync(
                lambda conn: SQLModel.metadata.create_all(bind=conn, checkfirst=True)
            )

        except OperationalError as e:
            if "already exists" in str(e):
                raise
    # 添加管理员用户
    async with async_session_maker() as session:
        # await UserService.create_user(session, "admin", "admin", is_superuser=True)  # type: ignore
        await init_permission(session)
        await dev_init_admin(session)


async def main():
    """
    主构建流程函数

    该函数协调整个应用的构建过程,按顺序执行以下步骤:
    1. 加密打包 Python 模块(app 和 plugins)到 SQLite 数据库文件
    2. 创建并准备 build 目录结构
    3. 复制必要的源文件和配置文件到 build 目录
    4. 注入动态生成的加密密钥到配置文件
    5. 对关键文件进行代码混淆
    6. 使用 PyInstaller 打包成可执行文件
    7. 清理临时构建文件
    8. 初始化数据库
    9. 构建 Vue 前端项目

    Returns:
        None: 无返回值
    """
    # 打包模块
    key = Encryption.generate_key()
    resources_path = Path("resources")
    if not resources_path.exists():
        resources_path.mkdir()
    app_packer = PythonToSQLite("./resources/app.mbank", key)
    app_packer.pack_directory("src/chongming/app", "app")
    app_packer.verify_package_structure()
    app_packer.delete_source_code(None)

    plugin_packer = PythonToSQLite("./resources/plugins.mbank", key)
    plugin_packer.pack_directory("src/plugins", "plugins")
    plugin_packer.verify_package_structure()
    plugin_packer.delete_source_code(None)

    # 创建 build 目录
    build_path = Path("build")
    if build_path.exists() and build_path.is_dir():
        shutil.rmtree("build")

    os.makedirs("build", exist_ok=True)

    # 复制 utils 文件夹到 build 文件夹
    utils_path = Path("utils")
    if utils_path.exists():
        target_utils_path = Path("build") / "utils"
        shutil.copytree(utils_path, target_utils_path, dirs_exist_ok=True)
        print(f"已复制 utils 文件夹到 {target_utils_path}")

    # 复制 resources 文件夹到 build 文件夹
    resources_path = Path("resources")
    if resources_path.exists():
        target_resources_path = Path("build") / "resources"
        shutil.copytree(resources_path, target_resources_path, dirs_exist_ok=True)
        print(f"已复制 resources 文件夹到 {target_resources_path}")

    print("模块打包完成")

    # 复制 main.py 到 build 文件夹
    shutil.copy("public/main.py", "build")
    shutil.copy("public/server.py", "build")
    # 复制 config.toml 到 build 文件夹
    shutil.copy("public/config.toml", "build")
    # 复制 utils 文件夹到 build 文件夹
    shutil.copytree("public/utils", "build/utils")

    with open("./build/utils/launch.py", "r", encoding="utf-8") as f:
        context = f.read()
        context = context.replace("key = None", f"key = '{key}'")
        with open("./build/utils/launch.py", "w", encoding="utf-8") as f:
            f.write(context)

    jwt_key = Encryption.generate_key()
    with open("./build/config.toml", "r", encoding="utf-8") as f:
        context = f.read()
        context = context.replace("your-secret-key-change-in-production", jwt_key)
        with open("build/config.toml", "w", encoding="utf-8") as f:
            f.write(context)

    # 混淆
    run_pyarmor_obfuscate()

    # 运行 PyInstaller
    run_pyinstaller()

    # 清理临时文件
    shutil.rmtree(r"build/build_temp", ignore_errors=True)
    shutil.rmtree(r"build/specs", ignore_errors=True)
    shutil.rmtree(r"build/utils", ignore_errors=True)
    shutil.rmtree(r"build/pyarmor_runtime_000000", ignore_errors=True)
    os.remove(r"build/main.py")
    os.remove(r"build/server.py")

    print("构建完成")

    # 初始化数据库
    await init_database()

    # 构建 vue 项目
    build_vue_web()


def build():
    """
    构建入口函数

    该函数作为整个构建流程的入口点,通过 asyncio.run() 启动异步主构建流程。

    Returns:
        None: 无返回值
    """
    asyncio.run(main())
