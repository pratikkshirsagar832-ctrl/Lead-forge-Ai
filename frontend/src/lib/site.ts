/** Canonical origin of the public site: https, NO www (nginx 301s www here). */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || 'https://hyperclients.online').replace(/\/+$/, '');
