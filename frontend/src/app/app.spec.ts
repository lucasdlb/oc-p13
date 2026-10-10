import { TestBed } from '@angular/core/testing';
import { App } from './app';
import { provideHttpClient } from '@angular/common/http';
import { of, Subject } from 'rxjs';

import {
  AnalyzePositionRequest,
  AnalyzePositionResponse,
  RagContextResponse,
  StockfishRunResponse,
} from './models/analysis';
import { AnalysisService } from './services/analysis';

function analysisStub(sessionId: string): AnalyzePositionResponse {
  return {
    opening: {
      eco: 'B00',
      name: "King's Pawn Game",
      matched: true,
      source: 'demo-opening-seed',
    },
    recommended_moves: [],
    masters_moves: [],
    masters_stats: { source: 'masters-opening-explorer', games: 0, white: 0, draws: 0, black: 0 },
    lichess_stats: {},
    source_confidence: {},
    rag_context: [],
    coach_explanation: 'demo',
    coach_status: 'generated',
    analysis_key: 'key-1',
    run_id: 'run-1',
    explorer_status: 'generated',
    stockfish_status: 'skipped',
    rag_status: 'generated',
    stockfish: null,
    videos: [],
    fallbacks_used: [],
    session_id: sessionId,
    cache: {},
  };
}

describe('App', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideHttpClient(),
        {
          provide: AnalysisService,
          useValue: {
            analyzePosition: () => of(analysisStub('session-1')),
            analyzeStockfishRun: () => of({ stockfish: null, stockfish_status: 'skipped', fallbacks_used: [] }),
            fetchRagContext: () => of({ rag_context: [], rag_status: 'generated', fallbacks_used: [] }),
            streamCoach: vi.fn(),
          },
        },
      ],
    }).compileComponents();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render the opening coach shell', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toContain("Analyse d'ouverture");
  });

  it('navigates the timeline with keyboard arrows', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    app.onMoveRequested({ from: 'e7', to: 'e5' });
    vi.runAllTimers();

    expect(app.currentIndex()).toBe(2);
    expect(app.totalMoves()).toBe(2);
    expect(app.sessionId()).toBe('session-1');

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));

    expect(app.currentIndex()).toBe(1);
    expect(app.moves()).toEqual(['e2e4']);
    expect(app.analysis()).not.toBeNull();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));

    expect(app.currentIndex()).toBe(0);
    expect(app.analysis()).toBeNull();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));

    expect(app.currentIndex()).toBe(0);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));

    expect(app.currentIndex()).toBe(1);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));

    expect(app.currentIndex()).toBe(2);
    expect(app.moves()).toEqual(['e2e4', 'e7e5']);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));

    expect(app.currentIndex()).toBe(2);
  });

  it('clears the board arrow when a structured recommended move is played', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;

    app.setMovePreview({ from: 'e2', to: 'e4' });
    expect(app.boardArrow()).toEqual({ from: 'e2', to: 'e4' });

    app.onRecommendedMoveRequested({ from: 'e2', to: 'e4' });

    expect(app.currentIndex()).toBe(1);
    expect(app.boardArrow()).toBeNull();
  });

  it('keeps one active question per position and separates question cache entries', () => {
    const service = TestBed.inject(AnalysisService);
    const requests: AnalyzePositionRequest[] = [];
    vi.spyOn(service, 'analyzePosition').mockImplementation((request) => {
      requests.push(request);
      return of(analysisStub('session-1'));
    });

    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    app.askQuestion('Que peuvent jouer les Noirs ?');
    app.askQuestion('Que peuvent jouer les Noirs ?');
    app.askQuestion('Pourquoi ce coup est-il bon ?');

    expect(requests).toHaveLength(2);
    expect(requests.map((request) => request.question ?? null)).toEqual([
      'Que peuvent jouer les Noirs ?',
      'Pourquoi ce coup est-il bon ?',
    ]);
    expect(app.question()).toBe('Pourquoi ce coup est-il bon ?');
  });

  it('submits a question from the coach form', () => {
    const service = TestBed.inject(AnalysisService);
    const requests: AnalyzePositionRequest[] = [];
    vi.spyOn(service, 'analyzePosition').mockImplementation((request) => {
      requests.push(request);
      return of(analysisStub('session-1'));
    });

    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();
    fixture.detectChanges();

    const input = fixture.nativeElement.querySelector('input[name="question"]') as HTMLInputElement;
    input.value = 'Pourquoi ce coup est-il bon ?';
    const form = fixture.nativeElement.querySelector('form.question-form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

    expect(requests.at(-1)?.question).toBe('Pourquoi ce coup est-il bon ?');
    expect(app.question()).toBe('Pourquoi ce coup est-il bon ?');
  });

  it('ignores keyboard navigation while focus is in a form control', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();

    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    input.remove();

    expect(app.currentIndex()).toBe(1);
  });

  it('reset clears the local timeline and session without a network call', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();

    expect(app.sessionId()).toBe('session-1');

    app.reset();

    expect(app.sessionId()).toBeNull();
    expect(app.currentIndex()).toBe(0);
    expect(app.totalMoves()).toBe(0);
    expect(app.moves()).toEqual([]);
    expect(app.analysis()).toBeNull();
    expect(app.error()).toBeNull();
  });

  it('restores a cached analysis when navigating back to an analyzed position', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();
    app.onMoveRequested({ from: 'e7', to: 'e5' });
    vi.runAllTimers();
    app.goBack();

    expect(app.analysis()).not.toBeNull();
    expect(app.analysis()!.session_id).toBe('session-1');
  });

  it('keeps Explorer visible while Stockfish is still pending and defers retrieval', () => {
    const explorer = new Subject<AnalyzePositionResponse>();
    const stockfish = new Subject<StockfishRunResponse>();
    const rag = new Subject<RagContextResponse>();
    const service = TestBed.inject(AnalysisService);
    vi.spyOn(service, 'analyzePosition').mockReturnValue(explorer.asObservable());
    vi.spyOn(service, 'analyzeStockfishRun').mockReturnValue(stockfish.asObservable());
    vi.spyOn(service, 'fetchRagContext').mockReturnValue(rag.asObservable());

    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();
    explorer.next({
      ...analysisStub('session-1'),
      coach_status: 'pending',
      stockfish_status: 'pending',
      rag_status: 'pending',
    });

    expect(app.analysis()?.opening.name).toBe("King's Pawn Game");
    expect(app.loading()).toBe(false);
    expect(app.stockfishLoading()).toBe(true);
    expect(app.ragLoading()).toBe(false);
    expect(service.fetchRagContext).not.toHaveBeenCalled();
  });

  it('explains why Stockfish was skipped instead of reporting it unavailable', async () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();
    fixture.detectChanges();

    const card = [...fixture.nativeElement.querySelectorAll('.stockfish-card p')]
      .at(-1) as HTMLElement;
    expect(card.textContent).toContain('Pas d’appel moteur nécessaire');
  });

  it('replaces the coach placeholder when the SSE stream fails', () => {
    const service = TestBed.inject(AnalysisService);
    const pendingAnalysis = {
      ...analysisStub('session-1'),
      coach_explanation: '',
      coach_status: 'pending' as const,
    };
    let streamHandlers: { error: () => void } | undefined;
    vi.spyOn(service, 'analyzePosition').mockReturnValue(of(pendingAnalysis));
    vi.spyOn(service, 'streamCoach').mockImplementation((_runId, handlers) => {
      streamHandlers = handlers;
      return { close: vi.fn() } as unknown as EventSource;
    });

    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();
    app.askQuestion('Pourquoi ce coup est-il bon ?');

    streamHandlers?.error();

    expect(app.analysis()?.coach_explanation).toBe('Explication indisponible pour cette position.');
    expect(app.analysis()?.coach_status).toBe('failed');
    expect(app.analysis()?.fallbacks_used).toContain('coach_stream_unavailable');
  });

  it('shows a neutral invitation before a coach explanation is requested', () => {
    const service = TestBed.inject(AnalysisService);
    vi.spyOn(service, 'analyzePosition').mockReturnValue(of({
      ...analysisStub('session-1'),
      coach_explanation: '',
      coach_status: 'pending',
    }));

    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.primary-note .state')?.textContent).toContain(
      'Pose une question sur cette position ou demande une explication de la position.',
    );
    expect(fixture.nativeElement.textContent).not.toContain('Question active :');
  });

  it('starts a coach explanation without a question', () => {
    const service = TestBed.inject(AnalysisService);
    vi.spyOn(service, 'analyzePosition').mockReturnValue(of({
      ...analysisStub('session-1'),
      coach_explanation: '',
      coach_status: 'pending',
    }));
    const streamCoach = vi.spyOn(service, 'streamCoach').mockReturnValue({ close: vi.fn() } as unknown as EventSource);

    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();
    fixture.detectChanges();

    const button = [...fixture.nativeElement.querySelectorAll('button')]
      .find((candidate) => candidate.textContent?.includes('Analyser la position')) as HTMLButtonElement;
    button.click();

    expect(streamCoach).toHaveBeenCalledWith('run-1', expect.anything());
  });

  it('hides provisional coach references until the final SSE result', () => {
    const service = TestBed.inject(AnalysisService);
    let streamHandlers: Parameters<AnalysisService['streamCoach']>[1] | undefined;
    vi.spyOn(service, 'analyzePosition').mockReturnValue(of({
      ...analysisStub('session-1'),
      coach_explanation: 'En attente',
      coach_status: 'pending',
    }));
    vi.spyOn(service, 'streamCoach').mockImplementation((_runId, handlers) => {
      streamHandlers = handlers;
      return { close: vi.fn() } as unknown as EventSource;
    });

    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    app.onMoveRequested({ from: 'e2', to: 'e4' });
    vi.runAllTimers();
    app.askQuestion('Pourquoi ce coup est-il bon ?');

    streamHandlers?.token('Jouez [[move:uci=e7e5,label=e5]] maintenant.');

    expect(app.analysis()?.coach_explanation).toBe('Jouez  maintenant.');

    streamHandlers?.done({
      explanation: 'Jouez [[move:uci=e7e5,label=e5]] maintenant.',
      coach_status: 'generated',
      fallbacks_used: [],
    });

    expect(app.analysis()?.coach_explanation).toContain('[[move:uci=e7e5,label=e5]]');
  });
});
