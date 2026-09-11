import { Tree } from 'antd';
import { useNavigate } from 'react-router-dom';
import type { LibraryInfo, DriveInfo, SlotInfo } from '../types';

/** 设备拓扑：带库 → 机器人/带机(含装载磁带)/槽位(含介质) */
export function DeviceTree({ lib, drives, slots }: {
  lib: LibraryInfo; drives: DriveInfo[]; slots: SlotInfo[];
}) {
  const nav = useNavigate();
  const treeData = [
    {
      title: `${lib.vendor} ${lib.model} (${lib.changer})`,
      key: 'lib',
      children: [
        { title: `Robot-01 (mtx @ /dev/${lib.changer})`, key: 'robot' },
        {
          title: `Drives (${drives.filter((d) => d.loaded_tape).length}/${drives.length} loaded)`,
          key: 'drives', children: drives.map((d) => ({
            title: `${d.model} /dev/${d.nst} ${d.loaded_tape ? '📼 ' + d.loaded_tape : '(Empty)'}`,
            key: `drive-${d.nst}`,
            isLeaf: true,
          })),
        },
        {
          title: `Slots (${slots.filter((s) => s.barcode).length}/${slots.length} occupied)`,
          key: 'slots', children: slots.map((s) => ({
            title: `Slot-${String(s.slot).padStart(3, '0')} ${s.barcode || '(Empty)'}`,
            key: `slot-${s.slot}`,
            isLeaf: true,
          })),
        },
      ],
    },
  ];
  return (
    <Tree
      defaultExpandAll showIcon={false} treeData={treeData}
      onSelect={(keys) => {
        const k = String(keys[0] || '');
        if (k.startsWith('drive-')) nav(`/drives/${k.replace('drive-', '')}`);
      }}
    />
  );
}
