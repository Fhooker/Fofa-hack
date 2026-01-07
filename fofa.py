#!/usr/bin/env python3
"""
Fofa 搜索工具 - 极简版
自动模式切换，一键搜索，稳定可靠，极速代理

使用:
    python fofa.py "app='Apache'"                 # 搜索（默认启用代理）
    python fofa.py "port=80" 50 json              # 50条结果，json格式
    python fofa.py --no-proxy "app='Apache'"      # 不使用代理（如果API可用）
    python fofa.py --help                         # 查看帮助
"""

import sys
import asyncio
from typing import Optional

# 当前目录支持
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fofa_hack.models.search import SearchConfig, OutputFormat
from fofa_hack.core.unified_client import AutoProxyUnifiedFofaClient
from fofa_hack.utils.output import save_results

# 简单RichUI支持（可选）
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    USE_RICH = True
except ImportError:
    USE_RICH = False
    console = None


def get_console():
    """获取控制台输出"""
    if USE_RICH:
        return Console()
    return None


def print_help():
    """打印帮助信息"""
    help_text = """
[bold cyan]Fofa 搜索工具 - 极简版[/bold cyan]

[bright_black]功能:[/bright_black]
  • 自动API/WEB模式切换
  • IP封禁时自动换代理（后台极速收集）
  • 默认启用自动代理，一键搜索
  • 支持JSON/CSV/TXT输出

[bright_black]使用方法:[/bright_black]
  [yellow]基本搜索（自动代理）:[/yellow]
    python fofa.py "app='Apache'"                    # 自动代理搜索
    python fofa.py "port=80" 50 json                 # 50条结果，json格式
    python fofa.py "title='管理后台'"                 # 搜索标题
    python fofa.py '"Ollama is running" && domain="true"' 100  # 复杂查询

  [yellow]不使用代理（如果API可用）:[/yellow]
    python fofa.py --no-proxy "app='Apache'"         # 不使用代理

  [yellow]批量/高级:[/yellow]
    python fofa.py "country='CN' && port=443" 100     # 100条结果
    python fofa.py --debug "query"                   # 调试模式

[bright_black]参数说明:[/bright_black]
  --no-proxy       禁用自动代理（默认启用）
  --debug          调试模式（显示详细日志）
  --help           显示帮助信息

[bright_black]输出格式:[/bright_black] json, csv, txt (默认: json)
[bright_black]结果数量:[/bright_black] 默认20条，可指定任意数量

[bright cyan]提示:[/bright cyan]
  1. 默认自动代理，无需配置，极速收集
  2. 被封禁时会立即自动换代理
  3. 复杂查询结果较少是正常现象
  4. 如API可用，建议使用 --no-proxy 加快速度
    """

    if USE_RICH:
        console = Console()
        console.print(Panel(help_text, title="Fofa 搜索工具", border_style="cyan"))
    else:
        print("Fofa 搜索工具 - 帮助")
        print("=" * 50)
        print("搜索: python fofa.py '查询语句' [数量] [格式]")
        print("禁用代理: python fofa.py --no-proxy '查询语句'")
        print("帮助: python fofa.py --help")


def show_stats(stats: dict):
    """显示统计信息"""
    if USE_RICH:
        console = Console()
        table = Table(title="搜索统计", show_header=False)
        table.add_row("总请求数", str(stats.get("total", 0)))
        table.add_row("成功", str(stats.get("success", 0)))
        table.add_row("失败", str(stats.get("failed", 0)))
        table.add_row("成功率", stats.get("rate", "0%"))
        table.add_row("封禁次数", str(stats.get("bans", 0)))
        table.add_row("当前模式", stats.get("mode", "unknown"))
        table.add_row("代理总数", str(stats.get("pool_count", 0)))

        pool_ready = stats.get("pool_ready")
        if pool_ready:
            table.add_row("代理状态", "✅ 就绪")
        else:
            table.add_row("代理状态", "⏳ 收集中")

        console.print(table)
    else:
        print("\n搜索统计:")
        print(f"总请求数: {stats.get('total', 0)}")
        print(f"成功: {stats.get('success', 0)}")
        print(f"失败: {stats.get('failed', 0)}")
        print(f"成功率: {stats.get('rate', '0%')}")
        print(f"封禁次数: {stats.get('bans', 0)}")
        print(f"当前模式: {stats.get('mode', 'unknown')}")
        print(f"代理总数: {stats.get('pool_count', 0)}")
        if stats.get("pool_ready"):
            print("代理状态: ✅ 就绪")
        else:
            print("代理状态: ⏳ 收集中")


def show_results(results):
    """显示前3条结果"""
    if not results:
        return

    if USE_RICH:
        console = Console()
        console.print("\n[cyan]前3条结果:[/cyan]")
        for i, r in enumerate(results[:3], 1):
            console.print(f"  {i}. {r.link or r.host}")
            if r.ip:
                console.print(f"     IP: {r.ip}:{r.port}")
            if r.city:
                console.print(f"     城市: {r.city}")
            if r.title:
                console.print(f"     标题: {r.title[:50]}")
    else:
        print("\n前3条结果:")
        for i, r in enumerate(results[:3], 1):
            print(f"  {i}. {r.link or r.host}")
            if r.ip:
                print(f"     IP: {r.ip}:{r.port}")
            if r.city:
                print(f"     城市: {r.city}")
            if r.title:
                print(f"     标题: {r.title[:50]}")


async def search(query: str, count: int = 20, output: str = 'json', use_proxy: bool = True, debug: bool = False):
    """执行搜索 - 智能主函数"""

    console = get_console()

    # 配置 - 优化的等待时间
    config = SearchConfig(
        keyword=query,
        end_count=count,
        time_sleep=0.5 if use_proxy else 1.0,  # 代理模式更快循环
        debug=debug
    )

    # 显示配置
    if console:
        console.print(Panel.fit(
            f"[bold cyan]🤖 Fofa 智能搜索[/bold cyan]\\\\n"
            f"[yellow]查询[/yellow]: {query}\\\\n"
            f"[yellow]数量[/yellow]: {count}\\\\n"
            f"[yellow]格式[/yellow]: {output}\\\\n"
            f"[yellow]代理[/yellow]: {'自动收集' if use_proxy else '无'}\\n"
            f"[yellow]提示[/yellow]: 复杂查询结果可能较少",
            title="配置"
        ))
    else:
        print(f"搜索: {query}, 数量: {count}, 格式: {output}, 代理: {use_proxy}")

    # 创建客户端 - 启动极速代理收集（后台）
    if console:
        console.print("[cyan]🚀 启动极速代理系统（后台收集）...[/cyan]")
    else:
        print("🚀 启动极速代理系统...")

    client = AutoProxyUnifiedFofaClient(config, auto_refresh_proxy=use_proxy)

    # 开始搜索（边搜边收集）
    if console:
        console.print("[cyan]🔍 开始搜索（代理后台加速中）...[/cyan]")
    else:
        print("🔍 开始搜索...")

    results = client.search_all(query, max_pages=20)

    # 分析结果质量并决定是否需要等待代理
    stats = client.get_stats()
    proxy_count = client.proxy_manager.count
    proxy_ready = client.proxy_manager.is_ready

    # 如果结果很少，且代理还没就绪，等待并重试
    if len(results) < min(count, 10) and use_proxy and not proxy_ready:
        if console:
            console.print("[yellow]⚠️  结果偏少，等待代理池收集完成（最多15秒）...[/yellow]")
            try:
                # 轻量等待，不阻塞
                for i in range(15):
                    if client.proxy_manager.is_ready and client.proxy_manager.count > 0:
                        break
                    await asyncio.sleep(1)
                    if i > 0 and i % 5 == 0 and console:
                        console.print(f"[cyan]⏳ 收集中... {client.proxy_manager.count}个代理[/cyan]")
            except:
                pass
        else:
            print("⚠️  等待代理收集...")
            for i in range(15):
                if client.proxy_manager.is_ready and client.proxy_manager.count > 0:
                    break
                await asyncio.sleep(1)

        # 代理就绪后重试（仅在结果过少时）
        if client.proxy_manager.is_ready and client.proxy_manager.count >= 3:
            if console:
                console.print(f"[bold green]✅ 代理池就绪！可用: {client.proxy_manager.count}个[/bold green]")
                console.print("[cyan]🔍 重新搜索提升结果质量...[/cyan]")
            else:
                print(f"✅ 代理池就绪！可用: {client.proxy_manager.count}个")
                print("🔍 重新搜索...")

            # 清空统计重新搜索
            client.total = 0
            client.success = 0
            client.failed = 0
            client.ban_count = 0

            new_results = client.search_all(query, max_pages=20)
            if len(new_results) > len(results):
                results = new_results
                if console:
                    console.print(f"[bold green]✅ 提升成功！获取到 {len(results)} 条结果[/bold green]")
                else:
                    print(f"✅ 提升成功！获取到 {len(results)} 条结果")
            else:
                if console:
                    console.print("[yellow]⚠️  未显著提升，使用首次结果[/yellow]")
                else:
                    print("⚠️  未显著提升，使用首次结果")
        else:
            if console and use_proxy:
                console.print("[yellow]⚠️  代理收集未完成，使用当前最佳结果[/yellow]")
            elif use_proxy:
                print("⚠️  代理收集未完成，使用当前最佳结果")

    # 处理结果
    if not results:
        if console:
            console.print("[red]❌ 未找到结果[/red]")
            if use_proxy and not proxy_ready:
                console.print("[cyan]提示: 代理仍在收集，可稍后重试[/cyan]")
        else:
            print("❌ 未找到结果")
            if use_proxy and not proxy_ready:
                print("提示: 代理仍在收集，可稍后重试")
        show_stats(client.get_stats())
        return ""

    # 保存结果
    filename = save_results(results, OutputFormat(output), f"fofa_results_{len(results)}")

    if console:
        console.print(f"[bold green]✅ 搜索完成！获取到 {len(results)} 条结果[/bold green]")
        console.print(f"[green]📁 文件: {filename}[/green]")
    else:
        print(f"✅ 搜索完成！获取到 {len(results)} 条结果")
        print(f"📁 文件: {filename}")

    show_stats(client.get_stats())
    show_results(results)

    return filename


async def interactive_search():
    """交互式搜索"""
    console = get_console()

    if console:
        console.print(Panel.fit(
            "[bold cyan]🤖 Fofa 智能搜索工具[/bold cyan]\\\\n"
            "极速代理收集，全自动模式\\\\n\\\\n"
            "支持功能:\\\\n"
            "- 自动从多个源收集代理\\\\n"
            "- IP封禁时自动秒切\\\\n"
            "- 智能模式（API/WEB）\\\\n\\\\n"
            "示例:\\\\n"
            '  app="Apache"\\\\n'
            '  port="80"\\\\n'
            '  "Ollama is running"\\\\n'
            '  country="CN"',
            title="欢迎使用"
        ))
    else:
        print("Fofa 智能搜索工具")
        print("=" * 30)
        print("示例: app='Apache', port=80, 'Ollama is running'")

    while True:
        if console:
            console.print("\\n[bold]请输入搜索关键词 (输入 q 退出):[/bold]")
        else:
            print("\n请输入搜索关键词 (输入 q 退出):")

        query = input("> ").strip()

        if query.lower() == 'q':
            if console:
                console.print("[cyan]👋 再见！[/cyan]")
            else:
                print("再见！")
            break

        if not query:
            if console:
                console.print("[yellow]⚠️  请输入关键词[/yellow]")
            else:
                print("⚠️  请输入关键词")
            continue

        # 输出格式
        if console:
            console.print("\\n[bold]选择输出格式:[/bold]")
            console.print("  1. JSON (默认)")
            console.print("  2. CSV (Excel)")
            console.print("  3. TXT (文本)")
            choice = input("选择 (1/2/3, 回车默认1): ").strip()
        else:
            choice = input("输出格式 (1=JSON, 2=CSV, 3=TXT, 回车默认1): ").strip()

        format_map = {'1': 'json', '2': 'csv', '3': 'txt'}
        output_format = format_map.get(choice, 'json')

        # 结果数量
        count_input = input("结果数量 (回车默认20): ").strip()
        try:
            count = int(count_input) if count_input else 20
        except ValueError:
            count = 20

        # 是否使用代理
        use_proxy_input = input("使用自动代理? (y/n, 回车默认y): ").strip().lower()
        use_proxy = use_proxy_input != 'n'

        try:
            await search(query, count, output_format, use_proxy)
            if console:
                console.print(f"\\n[bold green]✅ 搜索完成！[/bold green]")
            else:
                print("\n✅ 搜索完成！")
        except KeyboardInterrupt:
            if console:
                console.print("\\n[red]⚠️  搜索已取消[/red]")
            else:
                print("\n⚠️  搜索已取消")
        except Exception as e:
            if console:
                console.print(f"\\n[red]❌ 错误: {e}[/red]")
            else:
                print(f"\n❌ 错误: {e}")


def main():
    """主入口"""
    args = sys.argv[1:]

    # 无参数 - 显示帮助
    if not args:
        print_help()
        return

    # 帮助
    if '--help' in args or '-h' in args:
        print_help()
        return

    # 交互模式?
    if len(args) == 0 or (len(args) == 1 and args[0] == '-i'):
        if sys.stdin.isatty():
            asyncio.run(interactive_search())
            return

    # 解析参数
    debug = False
    query = None
    count = 20
    output = 'json'
    use_proxy = True  # 默认启用代理

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ['-p', '--proxy']:
            use_proxy = True
        elif arg in ['--no-proxy']:
            use_proxy = False
        elif arg in ['--debug']:
            debug = True
        elif arg in ['--help', '-h']:
            print_help()
            return
        elif arg.startswith('-'):
            i += 1
            continue
        else:
            if query is None:
                query = arg
            elif count == 20 and arg.isdigit():
                count = int(arg)
            elif output == 'json':
                output = arg.lower()
        i += 1

    if not query:
        print("❌ 请指定搜索关键词")
        print("使用: python fofa.py '查询语句' [数量] [格式]")
        return

    # 执行搜索
    try:
        asyncio.run(search(query, count, output, use_proxy, debug))
    except KeyboardInterrupt:
        print("\n⚠️  搜索已取消")
        sys.exit(0)
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()