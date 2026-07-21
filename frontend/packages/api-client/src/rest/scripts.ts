/** REST API: Scripts (stage management) */

import type { Script } from '@robots/shared-types';
import { apiGet, apiPost } from './client';

export function listScripts() {
  return apiGet<Script[]>('/scripts');
}

export function activateScript(scriptId: string) {
  return apiPost(`/scripts/${scriptId}/activate`);
}
