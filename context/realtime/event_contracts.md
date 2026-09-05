# Realtime Event Contracts

These contracts are conceptual and should be converted into TypeScript/.NET/MQL5-compatible schemas during Phase 02 and Phase 03.

## Envelope

Every realtime message should use a common envelope.

```json
{
  "messageId": "uuid",
  "correlationId": "uuid",
  "causationId": "uuid-or-null",
  "type": "execution.command.place_order",
  "schemaVersion": 1,
  "source": "risk-engine",
  "target": "mt5-agent:account-001",
  "sentAt": "2026-07-06T12:00:00.000Z",
  "payload": {}
}
```

## Required Envelope Fields

- `messageId` - unique id for deduplication.
- `correlationId` - links a workflow from signal to final report.
- `causationId` - previous message that caused this message.
- `type` - stable event or command name.
- `schemaVersion` - supports future evolution.
- `source` - producer.
- `target` - recipient or topic.
- `sentAt` - UTC timestamp.
- `payload` - typed data.

## Event Families

Market data:

- `market.tick`
- `market.candle.opened`
- `market.candle.closed`
- `market.spread.updated`
- `market.symbol.metadata`

Analysis:

- `analysis.market_context.updated`
- `analysis.liquidity.swept`
- `analysis.fvg.detected`
- `analysis.structure.shifted`
- `analysis.bias.updated`

Strategy:

- `strategy.signal.created`
- `strategy.signal.cancelled`
- `strategy.setup.expired`

Risk:

- `risk.state.updated`
- `risk.command.approved`
- `risk.command.rejected`
- `risk.lockout.enabled`
- `risk.lockout.cleared`

Execution commands:

- `execution.command.place_order`
- `execution.command.modify_position`
- `execution.command.close_position`
- `execution.command.close_all`
- `execution.command.cancel_order`

Execution reports:

- `execution.command.acknowledged`
- `execution.command.rejected`
- `execution.order.submitted`
- `execution.order.filled`
- `execution.order.partially_filled`
- `execution.order.failed`
- `execution.position.opened`
- `execution.position.modified`
- `execution.position.closed`

Agent:

- `agent.connected`
- `agent.heartbeat`
- `agent.disconnected`
- `agent.snapshot.account`
- `agent.snapshot.positions`
- `agent.error`

Dashboard:

- `dashboard.subscribe`
- `dashboard.unsubscribe`
- `dashboard.snapshot.requested`
- `dashboard.alert.acknowledged`

## Execution Command Payload Example

```json
{
  "accountId": "account-001",
  "agentId": "mt5-agent-001",
  "symbol": "XAUUSD",
  "side": "buy",
  "orderType": "market",
  "volume": 0.2,
  "stopLoss": 3295.0,
  "takeProfit": 3335.0,
  "riskPercent": 1.0,
  "strategyId": "ict-silver-bullet-v1",
  "expiresAt": "2026-07-06T12:00:05.000Z",
  "riskApprovalId": "risk-approval-001"
}
```

## Command Acknowledgement Payload Example

```json
{
  "commandId": "uuid",
  "agentId": "mt5-agent-001",
  "status": "accepted",
  "receivedAt": "2026-07-06T12:00:01.000Z"
}
```

## Execution Report Payload Example

```json
{
  "commandId": "uuid",
  "accountId": "account-001",
  "symbol": "XAUUSD",
  "status": "filled",
  "brokerOrderId": "123456",
  "brokerPositionId": "78910",
  "filledVolume": 0.2,
  "averagePrice": 3310.25,
  "stopLoss": 3295.0,
  "takeProfit": 3335.0,
  "brokerRetcode": "TRADE_RETCODE_DONE",
  "reportedAt": "2026-07-06T12:00:01.250Z"
}
```

## Idempotency Rules

- Execution agents must ignore duplicate `messageId`.
- Execution commands must carry a stable `commandId` in payload or use `messageId` as command id.
- Reports must include the original command id.
- Server must reconcile reports against intended commands.
- A reconnect must trigger snapshot resync before new execution commands are trusted.

