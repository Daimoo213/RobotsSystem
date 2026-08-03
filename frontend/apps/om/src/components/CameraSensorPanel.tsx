import { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, CircleAlert, LoaderCircle, Radio, RefreshCw, Square, Video, VideoOff } from 'lucide-react';
import { getDeviceCamera, setDeviceCameraEnabled } from '@robots/api-client';
import type { DeviceCameraState } from '@robots/api-client';

type ConnectionState = 'idle' | 'connecting' | 'connected' | 'error';

export function CameraSensorPanel({ deviceId }: { deviceId: string }) {
  const [camera, setCamera] = useState<DeviceCameraState | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [requestedEnabled, setRequestedEnabled] = useState<boolean | null>(null);
  const [viewerActive, setViewerActive] = useState(false);
  const [connection, setConnection] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const loadCamera = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const nextCamera = await getDeviceCamera(deviceId);
      setCamera(nextCamera);
      setError(null);
      if (requestedEnabled !== null && nextCamera.enabled === requestedEnabled) {
        setRequestedEnabled(null);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '无法读取摄像头状态');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [deviceId, requestedEnabled]);

  useEffect(() => {
    void loadCamera();
    const interval = window.setInterval(() => void loadCamera(true), requestedEnabled === null ? 15000 : 2500);
    return () => window.clearInterval(interval);
  }, [loadCamera, requestedEnabled]);

  useEffect(() => {
    if (!camera?.enabled) {
      setViewerActive(false);
      setConnection('idle');
    }
  }, [camera?.enabled]);

  useEffect(() => {
    const video = videoRef.current;
    const streamUrl = camera?.stream_url;
    if (!video || !viewerActive || !streamUrl) return;

    let hls: { destroy: () => void } | undefined;
    let disposed = false;
    setConnection('connecting');
    setError(null);
    video.muted = true;
    video.playsInline = true;

    const reportPlaybackError = () => {
      if (!disposed) {
        setConnection('error');
        setError('实时视频连接失败，请检查流媒体服务和网络');
      }
    };

    const playNatively = () => {
      video.src = streamUrl;
      video.load();
      void video.play().catch(reportPlaybackError);
    };

    const attachHls = async () => {
      const { default: Hls } = await import('hls.js');
      if (disposed) return;
      if (Hls.isSupported()) {
        const player = new Hls({ lowLatencyMode: true, backBufferLength: 30 });
        hls = player;
        player.on(Hls.Events.MANIFEST_PARSED, () => {
          void video.play().catch(reportPlaybackError);
        });
        player.on(Hls.Events.ERROR, (_event, data) => {
          if (data.fatal) reportPlaybackError();
        });
        player.loadSource(streamUrl);
        player.attachMedia(video);
      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        playNatively();
      } else {
        setConnection('error');
        setError('当前浏览器不支持该 HLS 视频流');
      }
    };

    if (camera.stream_protocol === 'hls') {
      void attachHls().catch(reportPlaybackError);
    } else {
      playNatively();
    }

    return () => {
      disposed = true;
      hls?.destroy();
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [camera?.stream_protocol, camera?.stream_url, viewerActive]);

  const handleToggle = async () => {
    if (!camera || submitting) return;
    const nextEnabled = !camera.enabled;
    if (!nextEnabled) setViewerActive(false);
    setSubmitting(true);
    setError(null);
    try {
      await setDeviceCameraEnabled(deviceId, nextEnabled);
      setRequestedEnabled(nextEnabled);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '摄像头命令下发失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleConnect = () => {
    if (!camera?.stream_url) {
      setError('摄像头已开启，正在等待网关提供可播放的视频流');
      return;
    }
    setViewerActive(true);
  };

  const state = requestedEnabled !== null
    ? '等待设备确认'
    : camera?.enabled
      ? camera.is_online ? '传感器在线' : '传感器离线'
      : '传感器已关闭';
  const stateColor = requestedEnabled !== null ? '#FFB33D' : camera?.enabled && camera.is_online ? '#34DF9A' : '#79A3BF';

  return (
    <section className="mb-3 rounded-lg border border-[rgba(91,183,255,0.15)] p-2.5" aria-label="机器人摄像头">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Camera size={14} className="shrink-0 text-[#2FD7FF]" />
          <span className="text-[12px] font-medium text-[#2FD7FF]">摄像头传感器</span>
          {!loading && camera?.available && <span className="truncate text-[11px]" style={{ color: stateColor }}>{state}</span>}
        </div>
        {loading ? (
          <LoaderCircle size={15} className="animate-spin text-[#79A3BF]" />
        ) : camera?.available ? (
          <button
            type="button"
            role="switch"
            aria-checked={camera.enabled}
            aria-label={camera.enabled ? '关闭摄像头传感器' : '开启摄像头传感器'}
            title={camera.enabled ? '关闭摄像头传感器' : '开启摄像头传感器'}
            disabled={submitting}
            onClick={() => void handleToggle()}
            className={`relative h-5 w-9 shrink-0 rounded-full border transition-colors disabled:cursor-wait disabled:opacity-60 ${camera.enabled ? 'border-[#34DF9A] bg-[rgba(52,223,154,0.24)]' : 'border-[#5A7A92] bg-[rgba(90,122,146,0.2)]'}`}
          >
            <span className={`absolute top-[3px] h-3 w-3 rounded-full bg-[#E6F6FF] transition-transform ${camera.enabled ? 'translate-x-[17px]' : 'translate-x-[3px]'}`} />
          </button>
        ) : null}
      </div>

      {!loading && !camera?.available && (
        <div className="flex items-center gap-2 py-2 text-[12px] text-[#5A7A92]">
          <VideoOff size={14} />
          <span>设备未上报摄像头模块</span>
        </div>
      )}

      {!loading && camera?.available && (
        <div className="space-y-2">
          <div className="flex items-center justify-between border-t border-[rgba(91,183,255,0.12)] pt-2">
            <span className="flex items-center gap-1.5 text-[11px] text-[#79A3BF]">
              <Radio size={12} style={{ color: camera.enabled && camera.is_online ? '#34DF9A' : '#5A7A92' }} />
              {camera.stream_protocol === 'hls' ? 'HLS 低延迟流' : camera.stream_protocol === 'mp4' ? '视频流' : '未提供视频流'}
            </span>
            {viewerActive ? (
              <button type="button" onClick={() => setViewerActive(false)} className="flex items-center gap-1 text-[11px] text-[#79A3BF] hover:text-[#E6F6FF]" title="停止实时查看">
                <Square size={12} /> 停止查看
              </button>
            ) : (
              <button type="button" disabled={!camera.enabled || !camera.is_online || requestedEnabled !== null} onClick={handleConnect} className="flex items-center gap-1 text-[11px] text-[#2FD7FF] hover:text-[#E6F6FF] disabled:cursor-not-allowed disabled:text-[#5A7A92]" title="连接实时画面">
                <Video size={12} /> 连接实时画面
              </button>
            )}
          </div>

          {viewerActive && (
            <div className="overflow-hidden rounded border border-[rgba(47,215,255,0.35)] bg-black">
              <div className="flex h-6 items-center justify-between border-b border-[rgba(47,215,255,0.2)] px-2 font-mono text-[10px] text-[#AECDE0]">
                <span className="flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${connection === 'connected' ? 'bg-[#34DF9A]' : connection === 'error' ? 'bg-[#FF5C6D]' : 'bg-[#FFB33D]'}`} /> LIVE</span>
                <span>{connection === 'connected' ? '已连接' : connection === 'error' ? '连接异常' : '连接中'}</span>
              </div>
              <div className="relative aspect-video bg-[#02060A]">
                <video ref={videoRef} className="h-full w-full object-contain" autoPlay muted playsInline onPlaying={() => setConnection('connected')} onError={() => setConnection('error')} />
                {connection !== 'connected' && (
                  <div className="absolute inset-0 flex items-center justify-center text-[12px] text-[#79A3BF]">
                    {connection === 'error' ? <CircleAlert size={15} className="mr-1.5 text-[#FF5C6D]" /> : <LoaderCircle size={15} className="mr-1.5 animate-spin text-[#2FD7FF]" />}
                    {connection === 'error' ? '无法播放视频流' : '正在连接视频流'}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-2 flex items-start gap-1.5 border-t border-[rgba(255,92,109,0.22)] pt-2 text-[11px] text-[#FF9AA5]">
          <CircleAlert size={13} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1">{error}</span>
          <button type="button" onClick={() => void loadCamera(true)} className="shrink-0 text-[#2FD7FF] hover:text-[#E6F6FF]" title="刷新摄像头状态"><RefreshCw size={13} /></button>
        </div>
      )}
    </section>
  );
}
