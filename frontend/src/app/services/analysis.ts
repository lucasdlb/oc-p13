import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';

import {
  AnalyzePositionRequest,
  AnalyzePositionResponse,
  CoachExplanationRequest,
  CoachExplanationResponse,
  CoachStreamDone,
  RagContextResponse,
  StockfishRunResponse,
} from '../models/analysis';

@Injectable({ providedIn: 'root' })
export class AnalysisService {
  private readonly http = inject(HttpClient);

  analyzePosition(request: AnalyzePositionRequest) {
    return this.http.post<AnalyzePositionResponse>('/api/analyze-position', request);
  }

  fetchCoachExplanation(request: CoachExplanationRequest) {
    return this.http.post<CoachExplanationResponse>('/api/coach-explanation', request);
  }

  analyzeStockfishRun(runId: string) {
    return this.http.post<StockfishRunResponse>('/api/stockfish/analyze-run', { run_id: runId });
  }

  fetchRagContext(runId: string) {
    return this.http.post<RagContextResponse>('/api/rag-context', { run_id: runId });
  }

  streamCoach(
    runId: string,
    handlers: {
      token: (text: string) => void;
      done: (result: CoachStreamDone) => void;
      error: () => void;
    },
  ): EventSource {
    const source = new EventSource(`/api/analysis-runs/${encodeURIComponent(runId)}/coach/stream`);
    source.addEventListener('token', (event) => {
      const data = JSON.parse((event as MessageEvent).data) as { text: string };
      handlers.token(data.text);
    });
    source.addEventListener('done', (event) => {
      handlers.done(JSON.parse((event as MessageEvent).data) as CoachStreamDone);
      source.close();
    });
    source.addEventListener('error', () => {
      handlers.error();
      source.close();
    });
    return source;
  }
}
