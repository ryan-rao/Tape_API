import { Tooltip, Modal, Button, Space } from 'antd';
import type { SlotInfo } from '../types';

/** 带库 Slot 物理可视化网格 —— 模拟物理带库槽位排布 */
export function SlotGrid({ slots, perRow = 6, onPick }: {
  slots: SlotInfo[]; perRow?: number;
  onPick?: (slot: SlotInfo, action: 'load' | 'move' | 'inventory') => void;
}) {
  const rows: SlotInfo[][] = [];
  for (let i = 0; i < slots.length; i += perRow) rows.push(slots.slice(i, i + perRow));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {rows.map((row, ri) => (
        <div key={ri} style={{ display: 'flex', gap: 8 }}>
          {row.map((s) => (
            <SlotCell key={s.slot} slot={s} onPick={onPick} />
          ))}
        </div>
      ))}
    </div>
  );
}

function SlotCell({ slot, onPick }: { slot: SlotInfo; onPick?: (s: SlotInfo, a: 'load' | 'move' | 'inventory') => void }) {
  const occupied = slot.status === 'Occupied';
  return (
    <Tooltip title={
      <div>
        <div>Element: 0x{slot.element.toString(16)} ({slot.element})</div>
        <div>Barcode: {slot.barcode || '-'}</div>
        <div>Media: {slot.media_type || '-'}</div>
        <div>Status: {slot.status}</div>
      </div>
    }>
      <div
        onClick={() => onPick?.(slot, 'inventory')}
        style={{
          width: 108, height: 84, border: '1px solid #d9d9d9', borderRadius: 6, cursor: 'pointer',
          background: occupied ? '#e6f4ff' : '#fafafa',
          borderColor: occupied ? '#1677ff' : '#d9d9d9',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 12 }}>S{String(slot.slot).padStart(2, '0')}</div>
        <div style={{ fontSize: 10, color: occupied ? '#1677ff' : '#999' }}>
          {occupied ? slot.barcode : 'EMPTY'}
        </div>
        {occupied && <div style={{ fontSize: 9, color: '#888' }}>{slot.media_type}</div>}
      </div>
    </Tooltip>
  );
}

/** Slot 详情弹窗 + 快捷操作 */
export function SlotDetailModal({ slot, open, onClose, onAction }: {
  slot: SlotInfo | null; open: boolean; onClose: () => void;
  onAction?: (slot: SlotInfo, action: 'load' | 'move' | 'inventory') => void;
}) {
  if (!slot) return null;
  return (
    <Modal open={open} title="Slot Information" footer={null} onCancel={onClose} width={420}>
      <div style={{ fontFamily: 'monospace', lineHeight: 2 }}>
        <div>Element: <b>{slot.element}</b> (0x{slot.element.toString(16)})</div>
        <div>Barcode: <b>{slot.barcode || '-'}</b></div>
        <div>Media: {slot.media_type || '-'}</div>
        <div>Status: <b style={{ color: slot.status === 'Occupied' ? '#1677ff' : '#999' }}>{slot.status}</b></div>
        <div>Drive: None</div>
      </div>
      <Space style={{ marginTop: 16 }}>
        <Button type="primary" disabled={slot.status !== 'Occupied'}
                onClick={() => onAction?.(slot, 'load')}>Load</Button>
        <Button disabled={slot.status !== 'Occupied'}
                onClick={() => onAction?.(slot, 'move')}>Move</Button>
        <Button onClick={() => onAction?.(slot, 'inventory')}>Inventory</Button>
      </Space>
    </Modal>
  );
}
