from binance_service.dataframe import Dataframe
from core.signal_logic import SignalLogic
from core.backtest_engine import BacktestEngine
from core.constants import BacktestConstants
from ui.tui import BacktestApp

"""
🥚 BINANCE EGGSHELL: BACKTEST MODE
"""

import os
import time
from datetime import datetime
from dotenv import load_dotenv

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.prompt import Prompt, IntPrompt, FloatPrompt


load_dotenv()

LOGO_ASCII = """
                 .#@@#.                                
                =@@@@@@=                               
               -@@@@@@@@=                              
              .@@@@@@@@@@:                             
              @@@@@@@@@@@%    ::.                      
             +%%@@@@@@@@@%    @@-                      
             @@@@@@@@@@@@%    @@-                      
            -@@@@@@@@@#***--- .                        
            %@@@@@@@@@:  .@@@    *%-                   
            @@@@@@@@@@:  .@@@    %%-                   
           -@@@@@@@@@@:  .@@@    ::.                   
           %@@@@@@@%%@%@@%   .++                       
           @@@@@@@@= .@@@%   .@@.                      
           @@@@@@@@= .@@@%   .%%                       
           @@@@@@@@@%%@##%***                          
           @@@@@@@@@@@#  *@@@                          
           @@@@@@@@@@@#  *@@%                          
           %@@@@@@@@@@%++%@@%                          
           -@@@@@@@@@@@@@@@@=                          
            @@@@@@@@@@@@@@@%                           
            -@@@@@@@@@@@@@@=                           
             +@@@@@@@@@%@@+                            
              :%@@@@@@@@%-                             
                :+#%%#+:                               
"""

console = Console()

def display_summary(results: dict):
    # Performance cards
    return Columns([
        Panel(f"[bold green]{results['total_return_pct']:.2f}%[/bold green]", title="Total Return", border_style="green"),
        Panel(f"[bold cyan]{results['win_rate']:.1f}%[/bold cyan]", title="Win Rate", border_style="cyan"),
        Panel(f"[bold yellow]{results['total_trades']}[/bold yellow]", title="Total Trades", border_style="yellow"),
        Panel(f"[bold white]${results['final_balance']:.2f}[/bold white]", title="Final Balance", border_style="white")
    ])

def display_trades_table(trades: list):
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Time", style="dim")
    table.add_column("Symbol", style="bold")
    table.add_column("Invested ($)", justify="right")
    table.add_column("Quantity", justify="right")
    table.add_column("Buy Price", justify="right")
    table.add_column("Sell Price", justify="right")
    table.add_column("Profit %", justify="right")
    table.add_column("Reason")

    # Show last 15 trades for brevity
    for t in trades[-15:]:
        color = "green" if t["profit_pct"] > 0 else "red"
        table.add_row(
            t["buy_time"].strftime("%Y-%m-%d %H:%M"),
            t["symbol"],
            f"${t['investment']:.2f}",
            f"{t['quantity']:.4f}",
            f"{t['buy_price']:.2f}",
            f"{t['sell_price']:.2f}",
            f"[{color}]{t['profit_pct']:.2f}%[/{color}]",
            t["reason"]
        )
    return table

def get_user_preferences():
    console.clear()
    console.print(Panel(
        "[bold cyan]── EGGSHELL CONFIGURATION ──[/bold cyan]\n[dim]SYSTEM STATUS: ONLINE[/dim]", 
        border_style="cyan", 
        padding=(1, 2)
    ))

    # 1. Select Active
    available_actives = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", "MATICUSDT"]
    active_choice = Prompt.ask(
        "Select [bold cyan]Asset[/bold cyan]",
        choices=available_actives + ["ALL"],
        default="BTCUSDT"
    )
    actives = available_actives if active_choice == "ALL" else [active_choice]

    # 2. Select Money
    starting_money = FloatPrompt.ask(
        "Initial [bold green]Balance ($)[/bold green]",
        default=1000.0
    )

    # 3. Position Size
    position_size_pct = FloatPrompt.ask(
        "Position [bold blue]Size (%)[/bold blue]",
        default=100.0
    )

    # 4. Select Timeframe
    available_intervals = ["15m", "1h", "4h", "1d"]
    interval = Prompt.ask(
        "Select [bold magenta]Timeframe[/bold magenta]",
        choices=available_intervals,
        default="1h"
    )

    # 5. Select History
    history_options = {
        "1M": "1 month ago",
        "3M": "3 months ago",
        "6M": "6 months ago",
        "1Y": "1 year ago",
        "2Y": "2 years ago",
        "2022": "1 Jan, 2022",
        "2021": "1 Jan, 2021",
        "2020": "1 Jan, 2020",
        "2018": "1 Jan, 2018"
    }
    history_choice = Prompt.ask(
        "History [bold yellow]Depth[/bold yellow]",
        choices=list(history_options.keys()),
        default="1Y"
    )
    start_date = history_options[history_choice]

    # 6. End Date
    end_date = Prompt.ask(
        "Enter [bold white]End Date[/bold white] (Optional, e.g., '1 Jan, 2024' or empty for now)",
        default=""
    )
    end_date = end_date if end_date else None

    return {
        "actives": actives,
        "starting_money": starting_money,
        "position_size_pct": position_size_pct,
        "interval": interval,
        "start_date": start_date,
        "end_date": end_date
    }

def run_backtest():
    prefs = get_user_preferences()
    
    console.clear()
    console.print(Panel.fit(
        f"[bold yellow]{LOGO_ASCII}[/bold yellow]\n"
        "[bold cyan]EGGSHELL BACKTESTER v1.0[/bold cyan]",
        border_style="magenta"
    ))
    
    console.print(Panel(
        f"[bold magenta]INITIATING BACKTEST SEQUENCE[/bold magenta]\n"
        f"[dim]ACTIVE: {', '.join(prefs['actives'])} | CORE_BAL: ${prefs['starting_money']} | RISK_LVL: {prefs['position_size_pct']}%[/dim]", 
        box=box.HEAVY, 
        border_style="cyan"
    ))
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        
        # 1. Fetch Data
        task1 = progress.add_task("[cyan]Downloading historical data...", total=100)
        binance_df = Dataframe(
            actives=prefs["actives"], 
            interval=prefs["interval"], 
            start_date=prefs["start_date"],
            end_date=prefs["end_date"]
        )
        progress.update(task1, completed=100)

        # 2. Calculate Indicators
        task2 = progress.add_task("[magenta]Calculating Elliot Bands & Indicators...", total=100)
        signals = SignalLogic(binance_df.df)
        progress.update(task2, completed=100)

        # 3. Run Simulation
        task3 = progress.add_task("[yellow]Simulating trades...", total=100)
        engine = BacktestEngine(
            signals.df, 
            initial_balance=prefs["starting_money"],
            position_size_pct=prefs["position_size_pct"]
        )
        results = engine.run()
        progress.update(task3, completed=100)

    # Display Results
    console.print("\n")
    console.print(Panel(display_summary(results), title="[bold white]PERFORMANCE SUMMARY[/bold white]", border_style="cyan", padding=(1, 2)))
    console.print("\n[bold magenta]Recent Trades Summary[/bold magenta]")
    console.print(display_trades_table(engine.trades))
    
    # Best/Worst Stats
    console.print(f"\n[green]Best Trade: {results['best_trade']:.2f}%[/green] | [red]Worst Trade: {results['worst_trade']:.2f}%[/red]")
    console.print(f"\n[bold yellow]Net Profit: ${results['net_profit']:.2f}[/bold yellow]")
    
    # Goodbye Banner
    console.print("\n")
    console.print(Panel.fit(
        "[bold cyan]THANKS FOR USING EGGSHELL BACKTESTER v1.0[/bold cyan]\n"
        "[dim]Happy Trading & Researching![/dim]",
        border_style="magenta",
        padding=(1, 5)
    ))

if __name__ == "__main__":
    import os
    if os.path.exists("reports/errors/error.log"):
        open("reports/errors/error.log", "w").close()

    # Launch TUI by default
    import sys
    if "--cli" in sys.argv:
        try:
            run_backtest()
        except Exception as e:
            import traceback
            import os
            os.makedirs("reports/errors", exist_ok=True)
            with open("reports/errors/error.log", "a") as f:
                f.write(f"{datetime.now()}: {e}\n{traceback.format_exc()}\n")
            console.print(f"\n[bold red]Backtest failed: {e}[/bold red]")
    else:
        app = BacktestApp()
        app.run()
        console.print("\n")
        console.print(Panel.fit(
            "[bold cyan]THANKS FOR USING EGGSHELL BACKTESTER v1.0[/bold cyan]\n"
            "[dim]See you in the next backtest session![/dim]",
            border_style="magenta",
            padding=(1, 5)
        ))