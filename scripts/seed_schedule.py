"""Idempotent draft schedule import. Never overwrites live edits or bookings."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from domain import epoch, retention_expiry
from store import DynamoStore
from botocore.exceptions import ClientError

store = DynamoStore()
rows = json.loads((Path(__file__).resolve().parents[1] / 'backend/schedule-draft.json').read_text())
expiry = retention_expiry(epoch('2026-12-06', 19))
for row in rows:
    row['id'] = str(row['id'])
    item = {**row, 'pk': 'SHIFT#'+row['id'], 'revision': 0, 'roster': [], 'open': True, 'overflowPercent': 0, 'location': 'Canal Park', 'attendance': {'incrementMinutes': 30, 'minMinutes': 30}, 'startAt': epoch(row['date'], row['start']), 'endAt': epoch(row['date'], row['end']), 'publicUntil': epoch('2026-12-07', 0), 'expiresAt': expiry}
    try:
        store.client.put_item(TableName=store.table, Item=store.encode(item), ConditionExpression='attribute_not_exists(pk)')
    except ClientError as error:
        if error.response['Error']['Code'] != 'ConditionalCheckFailedException':
            raise
registry = {'pk':'EVENT#2026','shiftIds':[str(r['id']) for r in rows],'expiresAt':expiry}
try:
    store.client.put_item(TableName=store.table, Item=store.encode(registry), ConditionExpression='attribute_not_exists(pk)')
except ClientError as error:
    if error.response['Error']['Code'] != 'ConditionalCheckFailedException':
        raise
print('Draft schedule initialized; existing records left unchanged.')
