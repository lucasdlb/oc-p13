import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';

import { AnalyzePositionRequest, AnalyzePositionResponse } from '../models/analysis';

@Injectable({ providedIn: 'root' })
export class AnalysisService {
  private readonly http = inject(HttpClient);

  analyzePosition(request: AnalyzePositionRequest) {
    return this.http.post<AnalyzePositionResponse>('/api/analyze-position', request);
  }
}
