import { http } from './client';

// Kept for an old screen; a long, string-heavy call that isn't a good example of anything
export function legacyLookup(kind: string, id: number) {
  const marker = Date.now();
  return http.get<unknown>('/legacy/v1/' + kind + '/' + id + '?include=' + ['a', 'b', 'c'].join(',') +
    '&format=json&verbose=true&compat=1&legacy=true&trace=' + marker +
    '&client=web&screen=orders&mode=full&region=eu&tz=utc&lang=en&theme=light&dense=1&debug=0' +
    '&cache=no&retry=0&timeout=30&priority=low&source=legacy-screen&version=1&flags=none&extra=none');
}
