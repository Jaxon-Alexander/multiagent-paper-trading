"""Command line entry point. Explicit --confirm-paper required for order submission."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
import sys

from dotenv import load_dotenv
from .broker import AlpacaPaperBroker
from .demo import snapshot as demo_snapshot
from .orchestrator import MultiAgentOrchestrator


def _write_trace(events, filename=None):
    if filename:
        path = Path(filename)
    else:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        path = Path('traces') / f'trace_{stamp}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events, indent=2, default=str), encoding='utf-8')
    return str(path)


def build_parser():
    parser = argparse.ArgumentParser(prog='market-agents', description='Multi-agent market analysis and Alpaca paper positions')
    sub = parser.add_subparsers(dest='command', required=True)
    analyze = sub.add_parser('analyze', help='Analyze market data and paper positions')
    analyze.add_argument('--symbols', nargs='+', required=True, help='One or more symbols, e.g. QQQ SQQQ')
    analyze.add_argument('--days', type=int, default=125, help='Calendar-day lookback (default: 125)')
    analyze.add_argument('--start', help='YYYY-MM-DD, explicit interval start')
    analyze.add_argument('--end', help='YYYY-MM-DD, explicit interval end')
    analyze.add_argument('--prompt', default='', help='Optional natural language context; ticker/dates remain CLI-owned')
    analyze.add_argument('--demo', action='store_true', help='Synthetic fixture; NO Gemini/Alpaca API calls')
    analyze.add_argument('--audit', action='store_true', help='Request optional Gemini Code Execution audit')
    analyze.add_argument('--trace', default=None, help='Optional trace JSON output path')
    portfolio = sub.add_parser('portfolio', help='Read current paper account/positions only')
    portfolio.add_argument('--demo', action='store_true', help='Synthetic example, NOT real account')
    preview = sub.add_parser('order-preview', help='Validate paper LIMIT order without submitting')
    submit = sub.add_parser('paper-order', help='Submit paper LIMIT order with explicit safeguards')
    for p in (preview, submit):
        p.add_argument('--symbol', required=True)
        p.add_argument('--side', choices=['buy', 'sell'], required=True)
        p.add_argument('--qty', type=int, required=True)
        p.add_argument('--limit-price', required=True, help='Positive dollar price')
    submit.add_argument('--confirm-paper', action='store_true', help='Required explicit approval for PAPER order')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    load_dotenv()
    try:
        if args.command == 'analyze':
            orchestrator = MultiAgentOrchestrator(demo=args.demo, audit=args.audit)
            result = orchestrator.analyze(args.symbols, days=args.days, prompt=args.prompt,
                                          start_date=args.start, end_date=args.end)
            print(json.dumps(result, indent=2, default=str))
            print(f'\nTrace: {_write_trace(orchestrator.events, args.trace)}', file=sys.stderr)
        elif args.command == 'portfolio':
            result = demo_snapshot() if args.demo else AlpacaPaperBroker().snapshot()
            print(json.dumps(result, indent=2, default=str))
        elif args.command in ('order-preview', 'paper-order'):
            # A paper-order call is NEVER available to the LLM agent function gateway.
            broker = AlpacaPaperBroker()
            kwargs = {'symbol': args.symbol, 'side': args.side, 'qty': args.qty,
                      'limit_price': args.limit_price}
            preview = broker.preview_limit_order(**kwargs)
            if args.command == 'order-preview':
                print(json.dumps(preview, indent=2))
            else:
                if not args.confirm_paper:
                    raise PermissionError('Missing --confirm-paper. Preview orders first.')
                result = broker.submit_limit_order(preview, confirmation=True)
                print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
