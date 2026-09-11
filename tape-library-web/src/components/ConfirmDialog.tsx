import { Modal, Input, Typography, Descriptions, Alert } from 'antd';
import { useState } from 'react';

const { Paragraph } = Typography;

/** 通用操作确认框（Mount/Unmount/Transfer/Read 等风险操作） */
export function ConfirmOperation({
  open, title, riskColor, items, confirmText = 'Confirm', onCancel, onConfirm,
}: {
  open: boolean; title: string; riskColor: 'orange' | 'green' | 'red';
  items: [string, string][]; confirmText?: string;
  onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <Modal
      open={open} title={`⚠ ${title}`} okText={confirmText} okButtonProps={{ danger: riskColor === 'red' }}
      onCancel={onCancel} onOk={onConfirm}
    >
      <Alert type={riskColor === 'red' ? 'error' : riskColor === 'orange' ? 'warning' : 'success'}
             message="此操作将作用于物理磁带库设备" showIcon style={{ marginBottom: 16 }} />
      <Descriptions column={1} size="small" bordered>
        {items.map(([k, v]) => <Descriptions.Item key={k} label={k}>{v}</Descriptions.Item>)}
      </Descriptions>
    </Modal>
  );
}

/** 写/擦除类破坏性操作的二次确认 —— 必须输入测试介质 Barcode 完全匹配才允许执行 */
export function ConfirmDestructive({
  open, tape, extra, onCancel, onConfirm,
}: {
  open: boolean; tape: string; extra: [string, string][];
  onCancel: () => void; onConfirm: () => void;
}) {
  const [input, setInput] = useState('');
  const match = input.trim() === tape && tape !== '';
  return (
    <Modal
      open={open} title="⚠ DESTRUCTIVE OPERATION" okText="Authorize Write"
      okButtonProps={{ danger: true, disabled: !match }} onCancel={() => { setInput(''); onCancel(); }}
      onOk={() => { if (match) { setInput(''); onConfirm(); } }}
    >
      <Alert type="error" showIcon style={{ marginBottom: 16 }}
        message="Writing data to tape may overwrite existing data."
        description="只能使用经批准的测试介质（TEST_MEDIA）。严禁使用生产介质。" />
      <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}
        items={[...extra, ['Tape (TEST_MEDIA)', tape]] as any} />
      <Paragraph type="secondary">输入测试磁带 Barcode 以确认授权（必须完全匹配）：</Paragraph>
      <Input placeholder="Enter tape barcode" value={input} onChange={(e) => setInput(e.target.value)} />
    </Modal>
  );
}
