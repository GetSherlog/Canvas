import React from 'react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { ConnectionComponentProps } from './shared.js';

export const CodeIndexConnectionForm: React.FC<ConnectionComponentProps> = ({ config, updateConfig, isTesting }) => {
  const handleUrlChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    updateConfig({ ...config, repo_url: event.target.value });
  };

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="repo-url">Repository URL</Label>
        <Input
          id="repo-url"
          type="url"
          placeholder="https://github.com/owner/repo.git"
          value={config.repo_url || ''}
          onChange={handleUrlChange}
          disabled={isTesting}
          required
        />
        <p className="text-sm text-muted-foreground mt-1">
          Enter the full URL of the Git repository (e.g., GitHub, GitLab).
        </p>
      </div>
    </div>
  );
};
