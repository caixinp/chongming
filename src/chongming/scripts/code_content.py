import os
import sys


def generate_markdown_from_py_files(directory, output_file):
    with open(output_file, "w", encoding="utf-8") as md_file:
        for root, dirs, files in os.walk(directory):
            # 排除 venv 目录
            dirs[:] = [d for d in dirs if d != ".venv"]
            dirs[:] = [d for d in dirs if d != ".vscode"]
            dirs[:] = [d for d in dirs if d != "node_modules"]
            dirs[:] = [d for d in dirs if d != "build"]
            dirs[:] = [d for d in dirs if d != "dist"]
            for file in files:
                if (
                    file.endswith(".py")
                    or file.endswith(".rs")
                    or file.endswith(".toml")
                    or file.endswith(".md")
                    or file.endswith(".css")
                    or file.endswith(".vue")
                    or file.endswith(".ts")
                    or file.endswith(".json")
                    or file.endswith(".html")
                    or file.endswith(".sh")
                    or file == "Dockerfile"
                ):
                    file_path = os.path.join(root, file)
                    if file == "output.md" or file == "package-lock.json":
                        continue
                    md_file.write(f"`{file_path}`\n")
                    md_file.write("```\n")
                    with open(file_path, "r", encoding="utf-8") as py_file:
                        md_file.write(py_file.read())
                    md_file.write("\n```\n\n")


if __name__ == "__main__":
    # 指定目录和输出文件名
    target_directory = sys.argv[1]  # 替换为你的目标目录
    output_markdown_file = "output.md"  # 输出的 Markdown 文件名

    generate_markdown_from_py_files(target_directory, output_markdown_file)
    print(f"Markdown 文件已生成：{output_markdown_file}")
