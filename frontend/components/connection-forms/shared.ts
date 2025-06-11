// Defines shared types and interfaces for connection forms

export interface ConnectionConfig {
  [key: string]: string | boolean | string[] | number | undefined; // Common configuration value types
}

export interface ConnectionComponentProps {
  config: ConnectionConfig;
  updateConfig: (newConfig: ConnectionConfig) => void;
  isTesting: boolean;
  // Add any other common props needed by connection forms
}
