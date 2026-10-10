import { Component, computed, HostListener, inject, signal, viewChild } from '@angular/core';
import type { Dests } from '@lichess-org/chessground/types';
import type { Subscription } from 'rxjs';

import { AnalysisPanelComponent } from './analysis-panel/analysis-panel';
import { ChessboardComponent } from './chessboard/chessboard';
import { LevelSelectorComponent } from './level-selector/level-selector';
import { AnalyzePositionResponse, PedagogicalLevel } from './models/analysis';
import { BoardMove } from './models/game';
import { MoveHistoryComponent } from './move-history/move-history';
import { AnalysisService } from './services/analysis';
import { GameSnapshot, GameStateService } from './services/game-state';

const COACH_STREAM_ERROR_TEXT = 'Explication indisponible pour cette position.';
const ANALYSIS_DEBOUNCE_MS = 700;

@Component({
  selector: 'app-root',
  imports: [
    AnalysisPanelComponent,
    ChessboardComponent,
    LevelSelectorComponent,
    MoveHistoryComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  readonly ratingBuckets = [0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500];
  private readonly analysisService = inject(AnalysisService);
  private readonly gameState = inject(GameStateService);
  private readonly board = viewChild(ChessboardComponent);
  private readonly initialGameState = this.gameState.snapshot();

  readonly level = signal<PedagogicalLevel>('debutant');
  readonly ratingMin = signal(1000);
  readonly ratingMax = signal(1400);
  readonly fen = signal(this.initialGameState.fen);
  readonly legalDests = signal<Dests>(this.initialGameState.legalDests);
  readonly legalMoves = signal<string[]>(this.initialGameState.legalMoves);
  readonly previewedMove = signal<BoardMove | null>(null);
  readonly previewedSquare = signal<string | null>(null);
  readonly boardArrow = computed(() => this.previewedMove());
  readonly pgn = signal('');
  readonly moves = signal<string[]>([]);
  readonly line = signal<string[]>([]);
  readonly currentIndex = signal(0);
  readonly totalMoves = signal(0);
  readonly analysis = signal<AnalyzePositionResponse | null>(null);
  readonly loading = signal(false);
  readonly stockfishLoading = signal(false);
  readonly ragLoading = signal(false);
  readonly coachStreaming = signal(false);
  readonly error = signal<string | null>(null);
  readonly question = signal<string | null>(null);
  readonly sessionId = signal<string | null>(null);

  private readonly analysisCache = new Map<string, AnalyzePositionResponse>();
  private analysisGeneration = 0;
  private explorerSubscription?: Subscription;
  private stockfishSubscription?: Subscription;
  private ragSubscription?: Subscription;
  private coachEventSource: EventSource | null = null;
  private analysisDebounce?: ReturnType<typeof setTimeout>;
  private coachRequested = false;
  private coachRunId?: string;

  setLevel(level: PedagogicalLevel): void {
    this.level.set(level);
    this.applyRatingPreset(level);
    this.refreshAnalysis();
  }

  setRatingMin(value: string | number): void {
    const rating = Number(value);
    this.ratingMin.set(rating);
    if (rating > this.ratingMax()) {
      this.ratingMax.set(rating);
    }
    this.refreshAnalysis();
  }

  setRatingMax(value: string | number): void {
    const rating = Number(value);
    this.ratingMax.set(rating);
    if (rating < this.ratingMin()) {
      this.ratingMin.set(rating);
    }
    this.refreshAnalysis();
  }

  askQuestion(value: string): void {
    const question = value.trim();
    if (!question || this.currentIndex() === 0) {
      return;
    }

    this.question.set(question);
    this.coachRequested = true;
    this.showAnalysis(true);
  }

  requestExplanation(): void {
    if (this.currentIndex() === 0) {
      return;
    }

    this.question.set(null);
    this.coachRequested = true;
    this.showAnalysis();
  }

  reset(): void {
    this.cancelPendingWork();
    this.previewedMove.set(null);
    this.previewedSquare.set(null);
    this.syncGameState(this.gameState.reset());
    this.analysis.set(null);
    this.error.set(null);
    this.question.set(null);
    this.sessionId.set(null);
    this.coachRequested = false;
  }

  playDemoMove(): void {
    this.reset();
    this.applyMove({ from: 'e2', to: 'e4' });
  }

  onMoveRequested(move: BoardMove): void {
    this.applyMove(move);
  }

  onRecommendedMoveRequested(move: BoardMove): void {
    this.applyMove(move);
  }

  onLineRequested(moves: BoardMove[]): void {
    this.applyLine(moves);
  }

  setMovePreview(move: BoardMove | null): void {
    this.previewedSquare.set(null);
    this.previewedMove.set(move);
  }

  setSquarePreview(square: string | null): void {
    this.previewedMove.set(null);
    this.previewedSquare.set(square);
  }

  goBack(): void {
    this.navigate(() => this.gameState.goBack());
  }

  goForward(): void {
    this.navigate(() => this.gameState.goForward());
  }

  @HostListener('document:keydown', ['$event'])
  onKeydown(event: KeyboardEvent): void {
    if (this.isFormTarget(event.target)) {
      return;
    }
    if (event.key === 'ArrowLeft' && this.currentIndex() > 0) {
      event.preventDefault();
      this.goBack();
    } else if (event.key === 'ArrowRight' && this.currentIndex() < this.totalMoves()) {
      event.preventDefault();
      this.goForward();
    }
  }

  private navigate(navigate: () => GameSnapshot | null): void {
    const snapshot = navigate();
    if (!snapshot) {
      return;
    }
    this.previewedMove.set(null);
    this.previewedSquare.set(null);
    this.question.set(null);
    this.coachRequested = false;
    this.syncGameState(snapshot);
    if (snapshot.currentIndex === 0) {
      this.cancelPendingWork();
      this.analysis.set(null);
      return;
    }
    this.showAnalysis();
  }

  private applyMove(move: BoardMove): void {
    this.previewedMove.set(null);
    this.previewedSquare.set(null);
    const result = this.gameState.applyMove(move);

    this.syncGameState(result.snapshot);

    if (result.ok) {
      this.question.set(null);
      this.coachRequested = false;
      this.showAnalysis();
      return;
    }

    this.error.set('Coup illegal pour la position courante.');
  }

  private applyLine(moves: BoardMove[]): void {
    this.previewedMove.set(null);
    this.previewedSquare.set(null);
    const result = this.gameState.applyLine(moves);

    this.syncGameState(result.snapshot);

    if (result.ok) {
      this.question.set(null);
      this.coachRequested = false;
      this.showAnalysis();
      return;
    }

    this.error.set('Suite de coups illegale pour la position courante.');
  }

  private refreshAnalysis(): void {
    if (this.currentIndex() === 0) {
      this.analysis.set(null);
      return;
    }
    this.showAnalysis();
  }

  private showAnalysis(immediate = false): void {
    this.cancelPendingWork();
    const cached = this.analysisCache.get(this.positionKey());
    if (cached) {
      this.analysis.set(cached);
      this.error.set(null);
      this.loading.set(false);
      this.startProgressive(cached, this.analysisGeneration, this.positionKey());
      return;
    }
    if (immediate) {
      this.analyze();
      return;
    }
    const generation = this.analysisGeneration;
    this.analysisDebounce = setTimeout(() => {
      this.analysisDebounce = undefined;
      if (generation === this.analysisGeneration) {
        this.analyze();
      }
    }, ANALYSIS_DEBOUNCE_MS);
  }

  private analyze(): void {
    this.cancelPendingWork();
    const generation = this.analysisGeneration;
    const cacheKey = this.positionKey();
    this.loading.set(true);
    this.error.set(null);

    this.explorerSubscription = this.analysisService
      .analyzePosition({
        fen: this.fen(),
        pgn: this.pgn() || 'Position initiale',
        moves: this.moves(),
        level: this.level(),
        question: this.question(),
        rating_min: this.ratingMin(),
        rating_max: this.ratingMax(),
        session_id: this.sessionId(),
      })
      .subscribe({
        next: (analysis) => {
          if (generation !== this.analysisGeneration) {
            return;
          }
          this.analysisCache.set(cacheKey, analysis);
          this.analysis.set(analysis);
          this.sessionId.set(analysis.session_id ?? null);
          this.loading.set(false);
          this.startProgressive(analysis, generation, cacheKey);
        },
        error: () => {
          if (generation !== this.analysisGeneration) {
            return;
          }
          this.error.set('Analyse indisponible. Verifie que le backend FastAPI est lance.');
          this.loading.set(false);
        },
      });
  }

  private startProgressive(
    analysis: AnalyzePositionResponse,
    generation: number,
    cacheKey: string,
  ): void {
    if (!analysis.run_id) {
      return;
    }
    const runId = analysis.run_id;

    const isFinished = (status: AnalyzePositionResponse['stockfish_status']): boolean =>
      status === 'generated' || status === 'fallback' || status === 'failed' || status === 'skipped';
    let stockfishDone = isFinished(analysis.stockfish_status);
    const maybeStartRequestedCoach = (): void => {
      if (
        generation === this.analysisGeneration &&
        stockfishDone &&
        this.coachRequested &&
        this.coachRunId !== runId &&
        this.analysis()?.coach_status !== 'generated' &&
        this.analysis()?.coach_status !== 'fallback'
      ) {
        this.coachRunId = runId;
        this.startRequestedCoach(runId, generation, cacheKey, isFinished(analysis.rag_status));
      }
    };

    if (!stockfishDone) {
      this.stockfishLoading.set(true);
      this.stockfishSubscription = this.analysisService.analyzeStockfishRun(analysis.run_id).subscribe({
        next: (result) => {
          if (generation !== this.analysisGeneration) {
            return;
          }
          this.stockfishLoading.set(false);
          stockfishDone = true;
          this.mergeAnalysis(generation, cacheKey, {
            stockfish: result.stockfish,
            stockfish_status: result.stockfish_status,
            fallbacks_used: result.fallbacks_used,
          });
          maybeStartRequestedCoach();
        },
        error: () => {
          if (generation !== this.analysisGeneration) {
            return;
          }
          this.stockfishLoading.set(false);
          stockfishDone = true;
          this.mergeAnalysis(generation, cacheKey, { stockfish_status: 'failed' });
          maybeStartRequestedCoach();
        },
      });
    } else {
      this.stockfishLoading.set(false);
    }

    this.ragLoading.set(false);
    maybeStartRequestedCoach();
  }

  private startRequestedCoach(
    runId: string,
    generation: number,
    cacheKey: string,
    ragDone: boolean,
  ): void {
    if (ragDone) {
      this.startCoachStream(runId, generation, cacheKey);
      return;
    }

    this.ragLoading.set(true);
    this.ragSubscription = this.analysisService.fetchRagContext(runId).subscribe({
      next: (result) => {
        if (generation !== this.analysisGeneration) {
          return;
        }
        this.ragLoading.set(false);
        this.mergeAnalysis(generation, cacheKey, {
          rag_context: result.rag_context,
          rag_status: result.rag_status,
          fallbacks_used: result.fallbacks_used,
        });
        this.startCoachStream(runId, generation, cacheKey);
      },
      error: () => {
        if (generation !== this.analysisGeneration) {
          return;
        }
        this.ragLoading.set(false);
        this.mergeAnalysis(generation, cacheKey, { rag_status: 'failed' });
        this.startCoachStream(runId, generation, cacheKey);
      },
    });
  }

  private startCoachStream(runId: string, generation: number, cacheKey: string): void {
    this.coachStreaming.set(true);
    let text = '';
    try {
      this.coachEventSource = this.analysisService.streamCoach(runId, {
        token: (chunk) => {
          if (generation !== this.analysisGeneration) {
            return;
          }
          text += chunk;
          this.mergeAnalysis(generation, cacheKey, { coach_explanation: this.maskStreamingReferences(text) });
        },
        done: (result) => {
          if (generation !== this.analysisGeneration) {
            return;
          }
          if (result.coach_status === 'pending') {
            this.markCoachUnavailable(generation, cacheKey);
            return;
          }
          this.coachStreaming.set(false);
          this.mergeAnalysis(generation, cacheKey, {
            coach_explanation: result.explanation,
            coach_status: result.coach_status,
            fallbacks_used: result.fallbacks_used,
          });
        },
        error: () => {
          if (generation === this.analysisGeneration) {
            this.markCoachUnavailable(generation, cacheKey);
          }
        },
      });
    } catch {
      this.markCoachUnavailable(generation, cacheKey);
    }
  }

  private maskStreamingReferences(text: string): string {
    return text
      .replace(/\[\[[a-z]+:[^\[\]]*\]\]/gi, '')
      .replace(/\[\[[a-z]+:[^\[\]]*$/gi, '');
  }

  private markCoachUnavailable(generation: number, cacheKey: string): void {
    this.coachStreaming.set(false);
    this.mergeAnalysis(generation, cacheKey, {
      coach_explanation: COACH_STREAM_ERROR_TEXT,
      coach_status: 'failed',
      fallbacks_used: ['coach_stream_unavailable'],
    });
  }

  private mergeAnalysis(
    generation: number,
    cacheKey: string,
    patch: Partial<AnalyzePositionResponse>,
  ): void {
    if (generation !== this.analysisGeneration) {
      return;
    }
    const current = this.analysis();
    if (!current) {
      return;
    }
    const updated: AnalyzePositionResponse = {
      ...current,
      ...patch,
      fallbacks_used: [...new Set([...current.fallbacks_used, ...(patch.fallbacks_used ?? [])])],
    };
    this.analysisCache.set(cacheKey, updated);
    this.analysis.set(updated);
  }

  private cancelPendingWork(): void {
    this.analysisGeneration += 1;
    if (this.analysisDebounce) {
      clearTimeout(this.analysisDebounce);
      this.analysisDebounce = undefined;
    }
    this.explorerSubscription?.unsubscribe();
    this.stockfishSubscription?.unsubscribe();
    this.ragSubscription?.unsubscribe();
    this.coachEventSource?.close();
    this.coachRunId = undefined;
    this.explorerSubscription = undefined;
    this.stockfishSubscription = undefined;
    this.ragSubscription = undefined;
    this.coachEventSource = null;
    this.loading.set(false);
    this.stockfishLoading.set(false);
    this.ragLoading.set(false);
    this.coachStreaming.set(false);
  }

  private positionKey(): string {
    return [
      this.fen(),
      this.level(),
      this.ratingMin(),
      this.ratingMax(),
      this.question() ?? '',
    ].join('|');
  }

  private syncGameState(state: GameSnapshot): void {
    this.fen.set(state.fen);
    this.legalDests.set(state.legalDests);
    this.legalMoves.set(state.legalMoves);
    this.pgn.set(state.pgn);
    this.moves.set(state.moves);
    this.line.set(state.line);
    this.currentIndex.set(state.currentIndex);
    this.totalMoves.set(state.totalMoves);
    this.syncBoardPosition(state);
  }

  private syncBoardPosition(state: GameSnapshot): void {
    this.board()?.setPosition(
      state.fen,
      state.turn,
      state.legalDests,
    );
  }

  private applyRatingPreset(level: PedagogicalLevel): void {
    const presets: Record<PedagogicalLevel, { min: number; max: number }> = {
      debutant: { min: 1000, max: 1400 },
      intermediaire: { min: 1600, max: 2000 },
      avance: { min: 2200, max: 2500 },
    };
    this.ratingMin.set(presets[level].min);
    this.ratingMax.set(presets[level].max);
  }

  private isFormTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) {
      return false;
    }
    const tag = target.tagName.toLowerCase();
    return (
      tag === 'input' ||
      tag === 'textarea' ||
      tag === 'select' ||
      tag === 'button' ||
      target.isContentEditable
    );
  }
}
