/** Estop overlay — full-screen red overlay for emergency stop state. */

interface EstopOverlayProps {
  active: boolean;
  source?: string;
  canRecover?: boolean;
  onRecover?: () => void;
}

const ESTOP_SOURCE_LABELS: Record<string, string> = { pm: '项目管理端', om: '运维端', safety: '安全系统', system: '系统' };

export function EstopOverlay({ active, source, canRecover, onRecover }: EstopOverlayProps) {
  if (!active) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center"
      style={{ backgroundColor: 'rgba(255,92,109,0.15)', backdropFilter: 'blur(2px)' }}
    >
      <div
        className="rounded-xl border-2 border-[#FF5C6D] bg-[rgba(20,5,8,0.9)] px-12 py-8 text-center"
        style={{ animation: 'blink 1.5s ease-in-out infinite' }}
      >
        <div className="text-[36px] font-bold text-[#FF5C6D]" style={{ textShadow: '0 0 20px rgba(255,92,109,0.6)' }}>
          全局急停已触发
        </div>
        <div className="mt-3 text-[16px] text-[#E6F6FF]">所有设备已停止运行</div>
        <div className="mt-2 text-[13px] text-[#79A3BF]">来源：{source ? ESTOP_SOURCE_LABELS[source] || '其他来源' : '未知'}</div>
        {canRecover ? (
          <button
            onClick={onRecover}
            className="mt-6 rounded-lg bg-[#34DF9A] px-8 py-2.5 text-[15px] font-medium text-[#050B13] transition-colors hover:bg-[#2FD7FF]"
          >
            恢复运行
          </button>
        ) : (
          <div className="mt-6 text-[14px] text-[#FFB33D]">请联系运维端执行恢复</div>
        )}
      </div>
      <style>{`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.6} }`}</style>
    </div>
  );
}
