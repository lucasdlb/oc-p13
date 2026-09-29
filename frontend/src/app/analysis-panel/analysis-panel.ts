import { Component, input } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';

import { AnalyzePositionResponse } from '../models/analysis';

@Component({
  selector: 'app-analysis-panel',
  imports: [DecimalPipe, PercentPipe],
  templateUrl: './analysis-panel.html',
  styleUrl: './analysis-panel.css',
})
export class AnalysisPanelComponent {
  readonly analysis = input<AnalyzePositionResponse | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);

  hasStats(): boolean {
    const stats = this.analysis()?.lichess_stats;
    return !!stats && 'games' in stats;
  }
}
