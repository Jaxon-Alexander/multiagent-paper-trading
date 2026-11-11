"""Hybrid multi-agent orchestrator: decisions by LLMs, immutable evidence by Python."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from typing import Any, Callable

from .agents import MarketDataAgent, TechnicalAnalysisAgent, PositionAnalysisAgent, RiskValidationAgent
from .audit import run_code_audit
from .broker import AlpacaPaperBroker
from .demo import snapshot as demo_snapshot, bars as demo_bars
from .extensions.sentiment import DisabledSentimentProvider, validate_sentiment_response
from .gemini import ask_json
from .indicators import build_analysis, calculate_technical_indicators, get_stock_data, validate_dates


class MultiAgentOrchestrator:
    """One request holds one shared state; no model can write to trusted numerical state."""

    def __init__(self, *, demo: bool = False, model: str | None = None, client=None,
                 broker=None, sentiment=None, data_provider=None,
                 today: date | None = None):
        self.demo = demo
        self.model = model
        self.client = client
        self.broker = broker
        self.sentiment = sentiment or DisabledSentimentProvider()
        self.data_provider = data_provider
        self.today = today or date.today()
        self.events: list[dict] = []
        self.agent_names: list[str] = []
        self.paths: list[str] = []
        if not demo:
            from dotenv import load_dotenv
            import os
            load_dotenv()
            self.model = self.model or os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite')
            if self.client is None:
                from google import genai
                key = os.getenv('GEMINI_API_KEY')
                if not key:
                    raise RuntimeError('GEMINI_API_KEY missing: configure .env before live analysis')
                self.client = genai.Client(api_key=key)
        else:
            self.model = self.model or 'scripted_demo_no_llm'
        self.market_agent = MarketDataAgent(self._gateway)
        self.technical_agent = TechnicalAnalysisAgent(self._gateway)
        self.position_agent = PositionAnalysisAgent(self._gateway)
        self.risk_agent = RiskValidationAgent(self._gateway)

    def record(self, event: str, **details):
        self.events.append({'step': len(self.events) + 1, 'event': event, **details})

    def _gateway(self, name: str, system: str, context: dict, schema: dict, trace) -> dict:
        if self.demo:
            if name == 'MarketDataAgent':
                result = {'needs_volume': True, 'reason': 'Synthetic example retrieves OHLCV bars'}
            elif name == 'TechnicalAnalysisAgent':
                result = {'explanation': 'Scripted demonstration; technical labels were calculated by Python.',
                          'requested_indicators': list(context['analysis']['indicators'])}
            elif name == 'PositionAnalysisAgent':
                result = {'explanation': 'Scripted demonstration of paper-position evaluation.',
                          'observations': ['Synthetic position and P/L; not a real account.']}
            else:
                result = {'notes': ['Synthetic example; deterministic flags remain authoritative.'],
                          'request_audit': False, 'reason': 'No independent audit in scripted demo'}
            trace('scripted_agent_response', agent=name, response=result)
            return result
        return ask_json(self.client, self.model, system, context, schema, trace, name)

    @staticmethod
    def _safe_text(value: Any, limit: int = 1200) -> str:
        if not isinstance(value, str):
            return ''
        value = value[:limit]
        # Free-form prose is advisory. Strip obvious execution instructions; the order API is never exposed.
        if re.search(r'\b(?:buy|sell|purchase|submit|execute|place)\s+(?:\d+\s+)?(?:shares|stocks|orders)\b', value, re.I):
            return '[Trading instruction omitted]'
        return value

    @staticmethod
    def _risk_flags(analysis: dict, position: dict | None, snapshot: dict | None) -> list[str]:
        flags = list(analysis['unusual_conditions'])
        i = analysis['indicators']
        if i['rsi_14'] is not None and i['rsi_14'] >= 70:
            flags.append('RSI is at or above 70 (project threshold).')
        if i['rsi_14'] is not None and i['rsi_14'] <= 30:
            flags.append('RSI is at or below 30 (project threshold).')
        if analysis['volatility'] == 'HIGH':
            flags.append('Annualized historical volatility is above 30% (project threshold).')
        if analysis['trend'] == 'UNKNOWN' and i['sma_20'] is not None and i['sma_50'] is not None:
            flags.append('Short-term and long-term trend signals conflict.')
        if analysis['current_price'] is None:
            flags.append('No historical price bars were available.')
        if position:
            if position.get('unrealized_pl') is not None and position['unrealized_pl'] < 0:
                flags.append('Current paper position has an unrealized loss.')
            if (position.get('portfolio_weight_pct') or 0) > 20:
                flags.append('Paper position exceeds 20% of portfolio equity (project threshold).')
        if analysis['ticker'] == 'SQQQ':
            flags.append('SQQQ seeks -3x the DAILY Nasdaq-100 return; long holding periods can diverge substantially.')
        held = {p['symbol'] for p in (snapshot or {}).get('positions', [])}
        if 'QQQ' in held and 'SQQQ' in held:
            flags.append('Paper portfolio holds QQQ and SQQQ simultaneously; exposures may offset but are not a stable hedge.')
        return list(dict.fromkeys(flags))

    def _snapshot(self) -> tuple[dict | None, str | None]:
        try:
            result = demo_snapshot() if self.demo else (self.broker or AlpacaPaperBroker()).snapshot()
            if result.get('paper') is not True:
                raise RuntimeError('Broker returned an account that was not verified as paper')
            self.record('paper_broker_snapshot', source=result['source'],
                        positions=len(result['positions']), account=result['account'])
            return result, None
        except Exception as exc:
            self.record('paper_broker_error', error=str(exc)[:300])
            return None, 'Paper account and positions unavailable; position analysis is incomplete.'

    def _stock(self, ticker: str, start: date, end: date) -> tuple[dict, str | None]:
        try:
            if self.data_provider:
                stock = self.data_provider(ticker, start.isoformat(), end.isoformat())
            elif self.demo:
                stock = demo_bars(ticker, start, end)
            else:
                stock = get_stock_data(ticker, start.isoformat(), end.isoformat())
            if stock.get('ticker') != ticker:
                raise ValueError('Data provider returned an unexpected ticker')
            self.record('historical_data', ticker=ticker, count=len(stock.get('bars', [])),
                        source=stock.get('source'), feed=stock.get('feed'))
            return stock, None
        except Exception as exc:
            self.record('historical_data_error', ticker=ticker, error=str(exc)[:350])
            return {'ticker': ticker, 'start_date': start.isoformat(), 'end_date': end.isoformat(),
                    'source': 'UNAVAILABLE', 'feed': None, 'bars': []}, str(exc)[:200]

    def analyze(self, symbols: list[str], *, days: int = 125, prompt: str = '',
                start_date: str | None = None, end_date: str | None = None) -> dict:
        self.events, self.agent_names, self.paths = [], [], []
        if not symbols or len(symbols) > 15:
            raise ValueError('Provide 1 to 15 symbols')
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 730:
            raise ValueError('days must be an integer from 1 to 730')
        end = date.fromisoformat(end_date) if end_date else self.today
        start = date.fromisoformat(start_date) if start_date else end - timedelta(days=days)
        names = []
        for symbol in symbols:
            name, _, _ = validate_dates(symbol, start.isoformat(), end.isoformat())
            if name not in names:
                names.append(name)
        self.record('request', symbols=names, start=start.isoformat(), end=end.isoformat(),
                    mode='OFFLINE_SCRIPTED_SYNTHETIC' if self.demo else 'LIVE_GEMINI_ALPACA_PAPER',
                    prompt=prompt[:600], model=self.model)
        broker, broker_error = self._snapshot()
        reports = {}
        for symbol in names:
            self.record('start_symbol', symbol=symbol)
            market_context = {'ticker': symbol, 'start_date': start.isoformat(),
                              'end_date': end.isoformat(), 'request': prompt[:600],
                              'instruction': 'Ticker and dates already validated by Python. Do not modify.'}
            try:
                plan = self.market_agent.run(market_context, self.record)
            except Exception as exc:
                self.record('agent_fallback', agent='MarketDataAgent', error=str(exc)[:200])
                plan = {'needs_volume': True, 'reason': 'Fallback: requested historical OHLCV bars'}
            self.agent_names.append('MarketDataAgent')
            self.paths.append(f'{symbol}:market_plan')
            stock, data_error = self._stock(symbol, start, end)
            self.paths.append(f'{symbol}:historical_data')
            bars = stock.get('bars', [])
            indicators = calculate_technical_indicators([b['close'] for b in bars]) if bars else None
            if bars:
                self.record('deterministic_calculation', symbol=symbol, indicators=indicators,
                            rule='Python-owned; never model-generated')
                self.paths.append(f'{symbol}:deterministic_calculation')
            else:
                self.record('dynamic_skip', symbol=symbol, stage='TechnicalAnalysisAgent', reason='No bars')
                self.paths.append(f'{symbol}:skip_technical_no_bars')
            analysis = build_analysis(stock, indicators)
            if data_error:
                analysis['uncertainty'] = ' '.join(filter(None, [analysis['uncertainty'],
                                                                'Historical-data request failed.']))
            position = next((p for p in broker['positions'] if p['symbol'] == symbol), None) if broker else None
            position_state = 'UNAVAILABLE' if broker is None else 'OPEN' if position else 'NONE'
            self.record('position_lookup', symbol=symbol, position_state=position_state)
            explanation = ''
            if bars:
                try:
                    response = self.technical_agent.run({'analysis': analysis, 'request': prompt[:600]}, self.record)
                    explanation = self._safe_text(response['explanation'])
                except Exception as exc:
                    self.record('agent_fallback', agent='TechnicalAnalysisAgent', error=str(exc)[:250])
                    explanation = 'LLM interpretation unavailable; deterministic results retained.'
                self.agent_names.append('TechnicalAnalysisAgent')
                self.paths.append(f'{symbol}:technical_analysis')
            position_explanation = ''
            if position is not None:
                try:
                    response = self.position_agent.run({'analysis': analysis, 'paper_position': position,
                                                        'paper_account': broker['account']}, self.record)
                    position_explanation = self._safe_text(response['explanation'])
                except Exception as exc:
                    self.record('agent_fallback', agent='PositionAnalysisAgent', error=str(exc)[:250])
                    position_explanation = 'Paper-position interpretation unavailable.'
                self.agent_names.append('PositionAnalysisAgent')
                self.paths.append(f'{symbol}:position_analysis')
            else:
                self.record('dynamic_skip', symbol=symbol, stage='PositionAnalysisAgent',
                            reason='No position' if broker else 'Paper account unavailable')
                self.paths.append(f'{symbol}:skip_position_agent')
            # Optional adapter: the disabled default produces UNKNOWN, not fabricated sentiment.
            try:
                sentiment = self.sentiment.analyze(symbol, {'analysis': analysis,
                                                              'paper_position': position})
                validate_sentiment_response(sentiment, ticker=symbol)
            except Exception as exc:
                self.record('sentiment_error', symbol=symbol, error=str(exc)[:250])
                sentiment = DisabledSentimentProvider().analyze(symbol, {})
            flags = self._risk_flags(analysis, position, broker)
            # Only numerical verification is audited; model decides whether the cost is justified.
            audit_available = bool(len(bars) >= 31 and self.client is not None and not self.demo
                                   and indicators is not None and all(
                                       indicators.get(k) is not None
                                       for k in ('sma_20', 'rsi_14', 'volatility_30d')))
            analysis['unusual_conditions'] = list(dict.fromkeys(analysis['unusual_conditions'] + flags))
            try:
                risk = self.risk_agent.run({'ticker': symbol, 'analysis': analysis,
                                            'position_state': position_state, 'paper_position': position,
                                            'deterministic_flags': flags, 'sentiment': sentiment,
                                            'audit_context': {
                                                'available': audit_available,
                                                'price_bar_count': len(bars),
                                                'independent_checks': ['sma_20', 'rsi_14', 'volatility_30d'],
                                                'note': 'Gemini Code Execution checks calculations only; it cannot place trades.'},
                                            'technical_interpretation': explanation,
                                            'position_interpretation': position_explanation}, self.record)
            except Exception as exc:
                self.record('agent_fallback', agent='RiskValidationAgent', error=str(exc)[:250])
                risk = {'notes': ['LLM risk review unavailable; deterministic flags retained.'],
                        'request_audit': False, 'reason': 'Model unavailable'}
            self.agent_names.append('RiskValidationAgent')
            self.paths.append(f'{symbol}:risk_review')
            # Gemini's RiskValidationAgent makes the audit decision; Python gates safe execution.
            requested = risk.get('request_audit') is True
            decision_reason = self._safe_text(risk.get('reason', ''), 400)
            self.record('audit_decision', symbol=symbol, source='RiskValidationAgent',
                        requested=requested, available=audit_available,
                        reason=decision_reason, rsi_14=analysis['indicators']['rsi_14'],
                        historical_bars=len(bars))
            self.paths.append(f'{symbol}:audit_decision')
            audit = {'trigger': 'risk_agent' if requested else 'none',
                     'status': 'not_requested', 'executed': False, 'verified': None,
                     'reason': 'RiskValidationAgent did not request a calculation audit.',
                     'decision_reason': decision_reason}
            if requested and not audit_available:
                audit.update(status='skipped',
                             reason='Independent audit requires at least 31 price bars, '
                                    'complete indicators, and a live Gemini client.')
                self.record('audit_skipped', symbol=symbol, reason=audit['reason'])
                self.paths.append(f'{symbol}:skip_audit_unavailable')
            elif requested:
                self.paths.append(f'{symbol}:independent_code_audit')
                result = run_code_audit(self.client, self.model,
                                        stock, indicators, self.record)
                audit.update(result)
                if audit['verified'] is not True:
                    analysis['uncertainty'] = ' '.join(filter(None, [analysis['uncertainty'],
                                                                    'Independent audit was not verified.']))
            status = 'INSUFFICIENT' if not bars else 'REVIEW' if flags or (audit['verified'] is False) else 'VALID'
            if data_error or broker_error:
                status = 'REVIEW' if bars else 'INSUFFICIENT'
            reports[symbol] = {
                'analysis': analysis,
                'technical_interpretation': explanation,
                'paper_position': {'state': position_state, 'data': position,
                                   'interpretation': position_explanation,
                                   'uncertainty': broker_error},
                'sentiment': sentiment,
                'risk_review': {'status': status, 'deterministic_flags': flags,
                                'agent_notes': [self._safe_text(n, 400) for n in risk['notes']][:5],
                                'audit': audit},
            }
            self.record('finish_symbol', symbol=symbol, status=status)
        held = {p['symbol'] for p in broker['positions']} if broker else set()
        combined_flags = []
        if 'QQQ' in held and 'SQQQ' in held:
            combined_flags.append('Both QQQ and SQQQ held in paper account; no assumption of a perfect hedge.')
        return {
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'mode': 'OFFLINE_SCRIPTED_SYNTHETIC' if self.demo else 'LIVE_GEMINI_ALPACA_PAPER',
            'paper_portfolio': broker,
            'paper_portfolio_uncertainty': broker_error,
            'symbols': reports,
            'portfolio_flags': combined_flags,
            'coordination': {'agents_invoked': list(dict.fromkeys(self.agent_names)),
                             'path': self.paths, 'calculation_source': 'deterministic_python',
                             'market_feed': 'synthetic' if self.demo else 'IEX',
                             'paper_only': True},
        }
