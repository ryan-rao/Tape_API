import { Progress, Descriptions, Tag, Space } from 'antd';
import type { TestSession } from '../types';

/** 实时测试进度面板（1s 轮询驱动） */
export function TestProgressView({ session }: { session: TestSession }) {
  const color = session.status === 'PASS' ? 'green' : session.status === 'FAIL' ? 'red' : 'blue';
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Tag color={color}>{session.status}</Tag>
        <Tag>{session.kind.toUpperCase()}</Tag>
        {session.verify && <Tag color="green">VERIFY {session.verify}</Tag>}
      </Space>
      <Progress
        percent={session.progress} status={session.status === 'FAIL' ? 'exception' : session.status === 'PASS' ? 'success' : 'active'}
        strokeColor={session.status === 'RUNNING' ? '#1677ff' : undefined}
      />
      <Descriptions column={3} size="small" bordered style={{ marginTop: 16 }}>
        <Descriptions.Item label="Drive">{session.drive}</Descriptions.Item>
        <Descriptions.Item label="Tape">{session.tape || '-'}</Descriptions.Item>
        <Descriptions.Item label="Transferred">{session.transferred_mb} / {session.size_mb} MiB</Descriptions.Item>
        <Descriptions.Item label="Throughput">{session.throughput_mbs} MiB/s</Descriptions.Item>
        <Descriptions.Item label="Elapsed">{String(Math.floor(session.elapsed_s / 60)).padStart(2, '0')}:{String(session.elapsed_s % 60).padStart(2, '0')}</Descriptions.Item>
        <Descriptions.Item label="Errors"><span style={{ color: session.errors ? 'red' : 'green' }}>{session.errors}</span></Descriptions.Item>
      </Descriptions>
      {session.commands.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {session.commands.map((c) => (
            <div key={c.command_id} style={{ fontFamily: 'monospace', fontSize: 12 }}>
              [{c.command_id}] {c.command} → exit={c.exit_code} ({c.duration_ms}ms)
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
