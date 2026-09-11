import { Tag, Tooltip } from 'antd';
import type { RiskLevel } from '../types';

const CONF: Record<RiskLevel, { color: string; icon: string; label: string; tip: string }> = {
  LEVEL_1: { color: 'green', icon: '🟢', label: 'READ ONLY', tip: '只读操作，不改变硬件状态' },
  LEVEL_2: { color: 'orange', icon: '🟡', label: 'DEVICE OPERATION', tip: '设备操作，将物理移动介质或定位磁带' },
  LEVEL_3: { color: 'red', icon: '🔴', label: 'DESTRUCTIVE', tip: '破坏性操作，将写入/擦除磁带数据' },
};

export function RiskTag({ level }: { level: RiskLevel }) {
  const c = CONF[level];
  return (
    <Tooltip title={c.tip}>
      <Tag color={c.color}>{c.icon} {c.label}</Tag>
    </Tooltip>
  );
}

export function riskConf(level: RiskLevel) { return CONF[level]; }
