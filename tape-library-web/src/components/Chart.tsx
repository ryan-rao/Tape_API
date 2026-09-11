// ECharts 按需引入（仅打包用到的模块，大幅减小体积）
import { useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { PieChart, BarChart, LineChart } from 'echarts/charts';
import { TooltipComponent, LegendComponent, GridComponent, TitleComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([PieChart, BarChart, LineChart, TooltipComponent, LegendComponent, GridComponent, TitleComponent, CanvasRenderer]);

export type ChartOption = echarts.EChartsCoreOption;

export function Chart({ option, height = 260 }: { option: ChartOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    inst.current = inst.current || echarts.init(ref.current);
    inst.current.setOption(option);
    const onResize = () => inst.current?.resize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [option]);
  return <div ref={ref} style={{ width: '100%', height }} />;
}
