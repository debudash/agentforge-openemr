/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SMART_CLIENT_ID?: string;
  readonly VITE_OPENEMR_SITE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
