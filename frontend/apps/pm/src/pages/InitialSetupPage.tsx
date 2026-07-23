import { useState } from 'react';
import { initialSetup, setAuthToken } from '@robots/api-client';

export function InitialSetupPage({ onInitialized }: { onInitialized: () => void }) {
  const [form, setForm] = useState({
    token: '', project_code: '', project_name: '', location: '',
    om_username: '', om_display_name: '', om_password: '',
    pm_username: '', pm_display_name: '', pm_password: '',
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const update = (key: keyof typeof form, value: string) => setForm((state) => ({ ...state, [key]: value }));
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setSaving(true); setError('');
    try {
      const result = await initialSetup(form.token, {
        project_code: form.project_code, project_name: form.project_name, location: form.location || undefined,
        om: { username: form.om_username, display_name: form.om_display_name, password: form.om_password },
        pm: { username: form.pm_username, display_name: form.pm_display_name, password: form.pm_password },
      });
      setAuthToken(result.token); onInitialized();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '初始化失败'); } finally { setSaving(false); }
  };
  const fields: Array<[keyof typeof form, string, string]> = [
    ['token', '初始化令牌', 'password'], ['project_code', '项目编码', 'text'], ['project_name', '项目名称', 'text'], ['location', '项目位置', 'text'],
    ['om_username', '运维端用户名', 'text'], ['om_display_name', '运维端显示名称', 'text'], ['om_password', '运维端密码（至少 12 位）', 'password'],
    ['pm_username', '项目管理端用户名', 'text'], ['pm_display_name', '项目管理端显示名称', 'text'], ['pm_password', '项目管理端密码（至少 12 位）', 'password'],
  ];
  return <div className="min-h-full overflow-y-auto bg-[#050B13] p-8 text-[#E6F6FF]"><form onSubmit={submit} className="mx-auto grid max-w-3xl grid-cols-2 gap-4 rounded-lg border border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.95)] p-6">
    <h1 className="col-span-2 text-[20px] font-bold">项目初始化</h1>
    {fields.map(([key, label, type]) => <label key={key} className="text-[12px] text-[#79A3BF]">{label}<input required={key !== 'location'} type={type} value={form[key]} onChange={(event) => update(key, event.target.value)} className="mt-1 block w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-2 text-[#E6F6FF] outline-none" /></label>)}
    {error && <div className="col-span-2 text-[12px] text-[#FF5C6D]">{error}</div>}
    <button disabled={saving} className="col-span-2 rounded bg-[#2FD7FF] py-2 text-[#050B13] disabled:opacity-50">{saving ? '提交中...' : '创建项目与账号'}</button>
  </form></div>;
}
