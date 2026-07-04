/* ============================================================
   Vendor Risk Assessor — Frontend Application
   Vanilla JS · No Frameworks
   ============================================================ */

'use strict';

class VendorRiskApp {
  /* ── Initialisation ──────────────────────────────────────── */

  constructor() {
    /** @type {string[]} */
    this.vendors = [];

    /** @type {object[]} */
    this.results = [];

    /** @type {boolean} */
    this.isAssessing = false;

    /** @type {EventSource|null} */
    this.eventSource = null;

    /** @type {string|null} */
    this.jobId = null;

    // Cache DOM references
    this.els = {
      input:         document.getElementById('vendor-input'),
      btnAdd:        document.getElementById('btn-add-vendor'),
      tagsContainer: document.getElementById('vendor-tags'),
      btnAssess:     document.getElementById('btn-assess'),
      progressSection: document.getElementById('progress-section'),
      progressTimeline: document.getElementById('progress-timeline'),
      agentFeed:     document.getElementById('agent-feed'),
      resultsSection: document.getElementById('results-section'),
      cardsGrid:     document.getElementById('vendor-cards-grid'),
      comparisonBody: document.getElementById('comparison-table-body'),
      statVendors:   document.getElementById('stat-vendors'),
      statAvgRisk:   document.getElementById('stat-avg-risk'),
      statHighest:   document.getElementById('stat-highest-risk'),
      themeToggle:   document.getElementById('theme-toggle'),
      statusChip:    document.getElementById('status-chip'),
      statusDot:     document.getElementById('status-chip-dot'),
      statusText:    document.getElementById('status-chip-text'),
      emptyState:    document.getElementById('empty-state'),
      btnExportJson: document.getElementById('btn-export-json'),
      btnExportMd:   document.getElementById('btn-export-md'),
    };

    this._bindEvents();
    this._initPresets();
    this._initTheme();
    this._initStatus();
    this._initExport();
  }

  /* ── Event Binding ───────────────────────────────────────── */

  _bindEvents() {
    // Input — Enter key
    this.els.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this._handleAddFromInput();
      }
    });

    // Add button
    this.els.btnAdd.addEventListener('click', () => this._handleAddFromInput());

    // Assess button
    this.els.btnAssess.addEventListener('click', () => this.startAssessment());
  }

  _initPresets() {
    document.querySelectorAll('.btn-preset').forEach((btn) => {
      btn.addEventListener('click', () => {
        const vendor = btn.dataset.vendor;
        if (this.addVendor(vendor)) {
          btn.classList.add('is-added');
        }
      });
    });
  }

  /* ── Theme ───────────────────────────────────────────────── */

  _initTheme() {
    const saved = localStorage.getItem('vra-theme') || 'dark';
    this._applyTheme(saved);
    if (this.els.themeToggle) {
      this.els.themeToggle.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        this._applyTheme(next);
        localStorage.setItem('vra-theme', next);
      });
    }
  }

  _applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    if (this.els.themeToggle) {
      this.els.themeToggle.textContent = theme === 'light' ? '☀️' : '🌙';
    }
  }

  /* ── Status chip ─────────────────────────────────────────── */

  async _initStatus() {
    if (!this.els.statusDot) return;
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      const components = data.components || [];
      const failed = components.filter((c) => !c.ok);
      const ok = data.healthy;

      this.els.statusDot.className = 'status-chip__dot ' + (ok ? 'status-chip__dot--ok' : 'status-chip__dot--warn');
      this.els.statusText.textContent = ok
        ? 'All systems go'
        : `${failed.length} issue${failed.length === 1 ? '' : 's'}`;

      if (this.els.statusChip) {
        this.els.statusChip.title = components
          .map((c) => `${c.ok ? '✓' : '✗'} ${c.name}: ${c.detail}`)
          .join('\n');
      }
    } catch (err) {
      this.els.statusDot.className = 'status-chip__dot status-chip__dot--error';
      this.els.statusText.textContent = 'Offline';
    }
  }

  /* ── Export ──────────────────────────────────────────────── */

  _initExport() {
    if (this.els.btnExportJson) {
      this.els.btnExportJson.addEventListener('click', () => this._exportReport('json'));
    }
    if (this.els.btnExportMd) {
      this.els.btnExportMd.addEventListener('click', () => this._exportReport('md'));
    }
  }

  _exportReport(format) {
    if (!this.jobId) {
      this.showNotification('Run an assessment first.', 'warning');
      return;
    }
    window.location.href = `/api/assess/${encodeURIComponent(this.jobId)}/export?format=${format}`;
  }

  /* ── Vendor Management ───────────────────────────────────── */

  _handleAddFromInput() {
    const name = this.els.input.value.trim();
    if (name) {
      this.addVendor(name);
      this.els.input.value = '';
      this.els.input.focus();
    }
  }

  /**
   * Add a vendor tag chip. Returns true if added, false if duplicate.
   * @param {string} name
   * @returns {boolean}
   */
  addVendor(name) {
    const normalised = name.trim();
    if (!normalised) return false;

    // Prevent duplicates (case-insensitive)
    if (this.vendors.some((v) => v.toLowerCase() === normalised.toLowerCase())) {
      this.showNotification(`"${normalised}" is already added.`, 'warning');
      return false;
    }

    this.vendors.push(normalised);
    this._renderTag(normalised);
    this._updateAssessButton();

    // Mark preset if applicable
    document.querySelectorAll('.btn-preset').forEach((btn) => {
      if (btn.dataset.vendor.toLowerCase() === normalised.toLowerCase()) {
        btn.classList.add('is-added');
      }
    });

    return true;
  }

  /**
   * Remove a vendor by name.
   * @param {string} name
   */
  removeVendor(name) {
    this.vendors = this.vendors.filter((v) => v.toLowerCase() !== name.toLowerCase());

    // Remove tag chip
    const tag = this.els.tagsContainer.querySelector(`[data-vendor="${CSS.escape(name)}"]`);
    if (tag) {
      tag.style.animation = 'fade-in-up 0.25s ease reverse forwards';
      tag.addEventListener('animationend', () => tag.remove(), { once: true });
    }

    // Un-mark preset
    document.querySelectorAll('.btn-preset').forEach((btn) => {
      if (btn.dataset.vendor.toLowerCase() === name.toLowerCase()) {
        btn.classList.remove('is-added');
      }
    });

    this._updateAssessButton();
  }

  _renderTag(name) {
    const tag = document.createElement('span');
    tag.className = 'vendor-tag';
    tag.dataset.vendor = name;
    tag.innerHTML = `
      ${this._escapeHtml(name)}
      <button class="vendor-tag__remove" type="button" aria-label="Remove ${this._escapeHtml(name)}">&times;</button>
    `;
    tag.querySelector('.vendor-tag__remove').addEventListener('click', () => this.removeVendor(name));
    this.els.tagsContainer.appendChild(tag);
  }

  _updateAssessButton() {
    const btn = this.els.btnAssess;
    const hasVendors = this.vendors.length > 0;
    btn.disabled = !hasVendors || this.isAssessing;
    btn.classList.toggle('is-ready', hasVendors && !this.isAssessing);
  }

  /* ── Assessment Flow ─────────────────────────────────────── */

  async startAssessment() {
    if (this.isAssessing || this.vendors.length === 0) return;

    this.isAssessing = true;
    this._updateAssessButton();

    // Reset UI
    this._clearResults();
    this._showProgressSection();

    // Define timeline steps
    this._initTimeline([
      'Initialising assessment pipeline',
      'Scanning CVE databases',
      'Gathering OSINT intelligence',
      'Calculating risk scores',
      'Generating reports',
    ]);

    this.addAgentMessage('orchestrator', 'Starting multi-agent risk assessment…', 'system');

    try {
      const response = await fetch('/api/assess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vendors: [...this.vendors] }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || errData.error || `Server error (${response.status})`);
      }

      const data = await response.json();

      if (data.job_id) {
        // Server supports SSE streaming
        this.jobId = data.job_id;
        this.connectSSE(data.job_id);
      } else if (data.reports || data.results) {
        // Synchronous response
        const reports = data.reports || data.results;
        this._completeAllTimelineSteps();
        this.addAgentMessage('system', 'Assessment complete.', 'system');
        this.renderResults(reports);
        this._finishAssessment();
      } else {
        throw new Error('Unexpected response format from server.');
      }
    } catch (err) {
      console.error('[VendorRiskApp] Assessment failed:', err);
      this.showNotification(`Assessment failed: ${err.message}`, 'error');
      this.addAgentMessage('system', `Error: ${err.message}`, 'system');
      this._finishAssessment();
    }
  }

  /**
   * Connect to a Server-Sent Events stream for real-time progress.
   * @param {string} jobId
   */
  connectSSE(jobId) {
    if (this.eventSource) {
      this.eventSource.close();
    }

    const url = `/api/assess/${encodeURIComponent(jobId)}/stream`;
    this.eventSource = new EventSource(url);

    this.eventSource.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        const eventType = payload.type || 'unknown';

        switch (eventType) {
          case 'progress':
            this.handleProgress(payload);
            break;

          case 'agent_activity':
            this.addAgentMessage(
              payload.vendor || 'system',
              payload.message || '',
              'info'
            );
            break;

          case 'result':
            if (payload.data) {
              this.results.push(payload.data);
            }
            this.addAgentMessage(
              payload.vendor || 'system',
              payload.message || 'Result received',
              'success'
            );
            break;

          case 'complete':
            this._completeAllTimelineSteps();
            this.addAgentMessage('system', payload.message || 'Assessment complete.', 'system');
            this.renderResults(this.results);
            this._finishAssessment();
            if (this.eventSource) {
              this.eventSource.close();
              this.eventSource = null;
            }
            break;

          case 'error':
            this.showNotification(`Error: ${payload.message || 'Unknown error'}`, 'error');
            this.addAgentMessage('system', `Error: ${payload.message}`, 'error');
            this._finishAssessment();
            if (this.eventSource) {
              this.eventSource.close();
              this.eventSource = null;
            }
            break;

          default:
            console.log('[SSE] Unknown event type:', eventType, payload);
        }
      } catch (err) {
        console.warn('[SSE] Failed to parse event:', e.data, err);
      }
    };

    this.eventSource.onerror = () => {
      if (this.eventSource && this.eventSource.readyState === EventSource.CLOSED) {
        this.showNotification('Lost connection to the assessment pipeline.', 'error');
        this._finishAssessment();
      }
    };
  }

  /**
   * Handle a progress event from the SSE stream.
   * @param {object} payload
   */
  handleProgress(payload) {
    const { step, status, agent, message, msg } = payload;

    // Update timeline step
    if (typeof step === 'number') {
      this._setTimelineStep(step, status || 'active');
    }

    // Add agent message
    if (message || msg) {
      this.addAgentMessage(agent || 'system', message || msg, payload.type || 'info');
    }
  }

  /* ── Results Rendering ───────────────────────────────────── */

  /**
   * Render all vendor report cards and summary.
   * @param {object[]} reports
   */
  renderResults(reports) {
    if (!reports || reports.length === 0) {
      this.showNotification('No results received.', 'warning');
      return;
    }

    this.results = reports;

    // Summary stats
    this.els.statVendors.textContent = reports.length;

    const scores = reports.map((r) => r.risk_score ?? r.overall_score ?? 0);
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    this.els.statAvgRisk.textContent = Math.round(avg);

    const maxScore = Math.max(...scores);
    const highestVendor = reports.find((r) => (r.risk_score ?? r.overall_score ?? 0) === maxScore);
    this.els.statHighest.textContent = highestVendor ? highestVendor.vendor_name || highestVendor.vendor || '—' : '—';
    this.els.statHighest.style.color = this._riskColor(maxScore);

    // Render cards with staggered animation
    this.els.cardsGrid.innerHTML = '';
    reports.forEach((report, i) => {
      const card = this.renderVendorCard(report);
      card.style.animationDelay = `${i * 0.12}s`;
      this.els.cardsGrid.appendChild(card);
    });

    // Comparison matrix
    this.renderComparisonMatrix(reports);

    // Show results section
    this.showSection('results-section');

    // Smooth scroll
    setTimeout(() => {
      this.els.resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 400);
  }

  /**
   * Create a vendor report card DOM element.
   * @param {object} report
   * @returns {HTMLElement}
   */
  renderVendorCard(report) {
    const vendorName  = report.vendor_name  || report.vendor || 'Unknown';
    const score       = report.risk_score   ?? report.overall_score ?? 0;
    const riskLevel   = report.risk_level   || this._riskLevel(score);
    const breakdown   = report.breakdown    || report.score_breakdown || {};
    const cves        = report.cve_findings || report.cves || [];
    const osint       = report.osint_findings || report.osint || [];
    const summary     = report.executive_summary || report.summary || '';
    const recommendations = report.recommendations || [];

    const card = document.createElement('div');
    card.className = 'vendor-card glass-card';

    // Determine badge class
    const badgeClass = this._riskBadgeClass(riskLevel);
    const riskColor  = this._riskColor(score);

    card.innerHTML = `
      <!-- Header -->
      <div class="vendor-card__header">
        <h3 class="vendor-card__name">${this._escapeHtml(vendorName)}</h3>
        <span class="vendor-card__badge ${badgeClass}">${this._escapeHtml(riskLevel)}</span>
      </div>

      <!-- Risk Gauge -->
      <div class="risk-gauge">
        <svg class="risk-gauge__svg" viewBox="0 0 200 200">
          <circle class="risk-gauge__track" cx="100" cy="100" r="85" />
          <circle
            class="risk-gauge__fill"
            cx="100" cy="100" r="85"
            stroke="url(#${this._gaugeGradientId(riskLevel)})"
            data-score="${score}"
          />
        </svg>
        <div class="risk-gauge__center">
          <div class="risk-gauge__score" style="color:${riskColor}">${score}</div>
          <div class="risk-gauge__label">Risk Score</div>
        </div>
      </div>

      <!-- Breakdown Bars -->
      <div class="breakdown" data-breakdown></div>

      <!-- Collapsible Sections -->
      <div class="collapsible-sections"></div>
    `;

    // Animate gauge
    const fillCircle = card.querySelector('.risk-gauge__fill');
    this.renderRiskGauge(score, riskColor, fillCircle);

    // Breakdown bars
    const breakdownContainer = card.querySelector('[data-breakdown]');
    if (Object.keys(breakdown).length > 0) {
      this.renderBreakdownBars(breakdown, breakdownContainer);
    } else {
      breakdownContainer.remove();
    }

    // Collapsible sections
    const sectionsContainer = card.querySelector('.collapsible-sections');
    const sections = [];

    if (summary) {
      sections.push({ title: 'Executive Summary', content: `<p class="collapsible__text">${this._escapeHtml(summary)}</p>` });
    }

    // Backend emits `cve_analysis` / `osint_analysis` as narrative strings.
    const cveAnalysis = report.cve_analysis || '';
    if (cveAnalysis) {
      sections.push({ title: 'CVE Analysis', content: `<p class="collapsible__text">${this._escapeHtml(cveAnalysis)}</p>` });
    }

    const osintAnalysis = report.osint_analysis || '';
    if (osintAnalysis) {
      sections.push({ title: 'OSINT Analysis', content: `<p class="collapsible__text">${this._escapeHtml(osintAnalysis)}</p>` });
    }

    if (cves.length > 0) {
      const cvesHtml = cves.slice(0, 10).map((c) => {
        const cveId   = c.cve_id || c.id || 'N/A';
        const sev     = c.severity || c.base_severity || 'N/A';
        const desc    = c.description || c.desc || '';
        const sevCol  = this._severityColor(sev);
        return `
          <div class="cve-item" style="border-left-color:${sevCol}">
            <span class="cve-item__id">${this._escapeHtml(cveId)}</span>
            <span class="cve-item__severity" style="background:${sevCol}22;color:${sevCol}">${this._escapeHtml(sev)}</span>
            ${desc ? `<div class="cve-item__desc">${this._escapeHtml(desc.substring(0, 200))}${desc.length > 200 ? '…' : ''}</div>` : ''}
          </div>
        `;
      }).join('');
      sections.push({ title: `CVE Analysis (${cves.length})`, content: cvesHtml });
    }

    if (osint.length > 0) {
      const osintHtml = `<ul class="collapsible__list">${osint.slice(0, 10).map((o) => {
        const text = typeof o === 'string' ? o : (o.finding || o.title || JSON.stringify(o));
        return `<li>${this._escapeHtml(text)}</li>`;
      }).join('')}</ul>`;
      sections.push({ title: `OSINT Findings (${osint.length})`, content: osintHtml });
    }

    if (recommendations.length > 0) {
      const recsHtml = `<ul class="collapsible__list">${recommendations.map((r) => {
        const text = typeof r === 'string' ? r : (r.recommendation || r.text || JSON.stringify(r));
        return `<li>${this._escapeHtml(text)}</li>`;
      }).join('')}</ul>`;
      sections.push({ title: 'Recommendations', content: recsHtml });
    }

    // Raw JSON — invaluable for debugging local-model output.
    sections.push({
      title: 'Raw JSON',
      content: `<div class="raw-json"><pre class="raw-json__pre">${this._escapeHtml(JSON.stringify(report, null, 2))}</pre></div>`,
    });

    sections.forEach((sec) => {
      sectionsContainer.appendChild(this._createCollapsible(sec.title, sec.content));
    });

    return card;
  }

  /**
   * Animate an SVG circular risk gauge.
   * @param {number} score    0–100
   * @param {string} color    CSS colour
   * @param {SVGCircleElement} circleEl
   */
  renderRiskGauge(score, color, circleEl) {
    const radius = 85;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference * (1 - score / 100);

    // Start fully hidden
    circleEl.style.strokeDasharray = `${circumference}`;
    circleEl.style.strokeDashoffset = `${circumference}`;

    // Trigger animation on next frame
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        circleEl.style.strokeDashoffset = `${offset}`;
      });
    });
  }

  /**
   * Render animated horizontal progress bars for score breakdown.
   * @param {object} breakdown  e.g. { "CVE Severity": 75, "OSINT Signals": 40, ... }
   * @param {HTMLElement} container
   */
  renderBreakdownBars(breakdown, container) {
    const colorClasses = ['cyan', 'purple', 'orange', 'red', 'green'];
    container.innerHTML = '<div class="breakdown__title">Score Breakdown</div>';

    Object.entries(breakdown).forEach(([label, value], idx) => {
      // Backend `score_breakdown` values are objects
      // ({ score, weight, weighted_score, description }); older shapes may be
      // plain numbers. Read the 0–100 factor score for the bar width.
      let numVal;
      let subLabel = '';
      if (value && typeof value === 'object') {
        numVal = Number(value.score ?? value.weighted_score ?? 0) || 0;
        if (value.description) subLabel = String(value.description);
      } else {
        numVal = (typeof value === 'number' ? value : parseFloat(value)) || 0;
      }
      const prettyLabel = subLabel || this._prettifyKey(label);
      const colorClass = colorClasses[idx % colorClasses.length];

      const item = document.createElement('div');
      item.className = 'breakdown__item';
      item.innerHTML = `
        <div class="breakdown__item-header">
          <span class="breakdown__item-label">${this._escapeHtml(prettyLabel)}</span>
          <span class="breakdown__item-value">${Math.round(numVal)}</span>
        </div>
        <div class="breakdown__bar">
          <div class="breakdown__bar-fill breakdown__bar-fill--${colorClass}" data-width="${numVal}"></div>
        </div>
      `;
      container.appendChild(item);
    });

    // Animate bars with stagger
    setTimeout(() => {
      container.querySelectorAll('.breakdown__bar-fill').forEach((bar, i) => {
        setTimeout(() => {
          bar.style.width = `${Math.min(Number(bar.dataset.width), 100)}%`;
        }, i * 100);
      });
    }, 300);
  }

  /**
   * Render the comparison matrix table.
   * @param {object[]} reports
   */
  renderComparisonMatrix(reports) {
    this.els.comparisonBody.innerHTML = '';

    reports.forEach((report) => {
      const vendorName = report.vendor_name || report.vendor || 'Unknown';
      const score      = report.risk_score ?? report.overall_score ?? 0;
      const riskLevel  = report.risk_level || this._riskLevel(score);
      const recommendations = report.recommendations || [];

      // Prefer the backend's machine-readable metrics block; fall back to any
      // structured arrays if present (older shapes).
      const metrics    = report.metrics || {};
      const cves       = report.cve_findings || report.cves || [];
      const osint      = report.osint_findings || report.osint || [];
      const cveCount     = metrics.total_cves ?? cves.length;
      const criticalCves = metrics.critical_count ?? cves.filter((c) => {
        const sev = (c.severity || c.base_severity || '').toUpperCase();
        return sev === 'CRITICAL';
      }).length;
      const osintSignals = (metrics.breach_count != null || metrics.compliance_issues != null || metrics.security_incidents != null)
        ? (metrics.breach_count || 0) + (metrics.compliance_issues || 0) + (metrics.security_incidents || 0)
        : osint.length;

      const topRec = recommendations.length > 0
        ? (typeof recommendations[0] === 'string' ? recommendations[0] : recommendations[0].text || recommendations[0].recommendation || '—')
        : '—';

      const row = document.createElement('tr');
      row.innerHTML = `
        <td style="font-weight:600;color:var(--text-primary)">${this._escapeHtml(vendorName)}</td>
        <td style="font-weight:600;color:${this._riskColor(score)}">${score}</td>
        <td><span class="vendor-card__badge ${this._riskBadgeClass(riskLevel)}">${this._escapeHtml(riskLevel)}</span></td>
        <td>${cveCount}</td>
        <td style="color:${criticalCves > 0 ? 'var(--risk-critical)' : 'var(--text-secondary)'}">${criticalCves}</td>
        <td>${osintSignals}</td>
        <td style="font-size:0.8rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${this._escapeHtml(topRec.substring(0, 60))}${topRec.length > 60 ? '…' : ''}</td>
      `;
      this.els.comparisonBody.appendChild(row);
    });
  }

  /* ── Agent Feed ──────────────────────────────────────────── */

  /**
   * Add an entry to the agent activity feed.
   * @param {string} agent
   * @param {string} message
   * @param {string} type
   */
  addAgentMessage(agent, message, type = 'info') {
    const item = document.createElement('div');
    item.className = 'agent-feed__item';

    const now = new Date();
    const ts  = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;

    const agentClass = this._agentColorClass(agent);

    item.innerHTML = `
      <span class="agent-feed__timestamp">${ts}</span>
      <span class="agent-feed__agent ${agentClass}">[${this._escapeHtml(agent)}]</span>
      <span class="agent-feed__message">${this._escapeHtml(message)}</span>
    `;

    this.els.agentFeed.appendChild(item);
    this.els.agentFeed.scrollTop = this.els.agentFeed.scrollHeight;
  }

  /* ── Timeline ────────────────────────────────────────────── */

  _initTimeline(steps) {
    this.els.progressTimeline.innerHTML = '';
    steps.forEach((label, idx) => {
      const step = document.createElement('div');
      step.className = 'timeline-step';
      step.dataset.stepIndex = idx;
      step.innerHTML = `
        <div class="timeline-step__dot"></div>
        <div class="timeline-step__label">${this._escapeHtml(label)}</div>
        <div class="timeline-step__meta"></div>
      `;
      if (idx === 0) step.classList.add('is-active');
      this.els.progressTimeline.appendChild(step);
    });
  }

  _setTimelineStep(index, status) {
    const steps = this.els.progressTimeline.querySelectorAll('.timeline-step');
    steps.forEach((step, i) => {
      step.classList.remove('is-active');
      if (i < index) {
        step.classList.add('is-complete');
      } else if (i === index) {
        step.classList.add(status === 'complete' ? 'is-complete' : 'is-active');
      }
    });
  }

  _completeAllTimelineSteps() {
    this.els.progressTimeline.querySelectorAll('.timeline-step').forEach((step) => {
      step.classList.remove('is-active');
      step.classList.add('is-complete');
    });
  }

  /* ── Section Visibility ──────────────────────────────────── */

  showSection(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('is-visible');
  }

  hideSection(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('is-visible');
  }

  _showProgressSection() {
    this.els.agentFeed.innerHTML = '';
    if (this.els.emptyState) this.els.emptyState.classList.add('is-hidden');
    this.showSection('progress-section');
    this.hideSection('results-section');
  }

  _clearResults() {
    this.results = [];
    this.els.cardsGrid.innerHTML = '';
    this.els.comparisonBody.innerHTML = '';
    this.els.statVendors.textContent = '0';
    this.els.statAvgRisk.textContent = '—';
    this.els.statHighest.textContent = '—';
  }

  _finishAssessment() {
    this.isAssessing = false;
    this._updateAssessButton();

    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  /* ── Notifications ───────────────────────────────────────── */

  /**
   * Show a toast notification.
   * @param {string} message
   * @param {'success'|'error'|'info'|'warning'} type
   */
  showNotification(message, type = 'info') {
    // Remove previous notification of same type
    document.querySelectorAll(`.notification--${type}`).forEach((n) => n.remove());

    const toast = document.createElement('div');
    toast.className = `notification notification--${type}`;

    const icons = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span> <span>${this._escapeHtml(message)}</span>`;

    document.body.appendChild(toast);

    // Auto-dismiss
    setTimeout(() => {
      toast.classList.add('is-leaving');
      toast.addEventListener('animationend', () => toast.remove(), { once: true });
    }, 4500);
  }

  /* ── Collapsible Helper ──────────────────────────────────── */

  _createCollapsible(title, contentHtml) {
    const wrapper = document.createElement('div');
    wrapper.className = 'collapsible';
    wrapper.innerHTML = `
      <button class="collapsible__trigger" type="button">
        <span>${this._escapeHtml(title)}</span>
        <span class="collapsible__icon">▼</span>
      </button>
      <div class="collapsible__content">${contentHtml}</div>
    `;

    wrapper.querySelector('.collapsible__trigger').addEventListener('click', () => {
      wrapper.classList.toggle('is-open');
    });

    return wrapper;
  }

  /* ── Utility Helpers ─────────────────────────────────────── */

  /**
   * Determine risk level label from numeric score.
   * @param {number} score
   * @returns {string}
   */
  _riskLevel(score) {
    if (score >= 80) return 'Critical';
    if (score >= 60) return 'High';
    if (score >= 40) return 'Medium';
    return 'Low';
  }

  /**
   * Return CSS colour for a risk score.
   * @param {number} score
   * @returns {string}
   */
  _riskColor(score) {
    if (score >= 80) return 'var(--risk-critical)';
    if (score >= 60) return 'var(--risk-high)';
    if (score >= 40) return 'var(--risk-medium)';
    return 'var(--risk-low)';
  }

  _riskBadgeClass(level) {
    const l = (level || '').toLowerCase();
    if (l === 'critical') return 'vendor-card__badge--critical';
    if (l === 'high')     return 'vendor-card__badge--high';
    if (l === 'medium')   return 'vendor-card__badge--medium';
    return 'vendor-card__badge--low';
  }

  _gaugeGradientId(level) {
    const l = (level || '').toLowerCase();
    if (l === 'critical') return 'gauge-gradient-critical';
    if (l === 'high')     return 'gauge-gradient-high';
    if (l === 'medium')   return 'gauge-gradient-medium';
    return 'gauge-gradient-low';
  }

  _severityColor(severity) {
    const s = (severity || '').toUpperCase();
    if (s === 'CRITICAL') return '#ef4444';
    if (s === 'HIGH')     return '#f97316';
    if (s === 'MEDIUM')   return '#eab308';
    return '#22c55e';
  }

  /**
   * Turn a snake_case breakdown key into a Title Case label.
   * e.g. "cve_critical" → "Cve Critical"; "avg_cvss" → "Avg Cvss".
   * @param {string} key
   * @returns {string}
   */
  _prettifyKey(key) {
    return String(key || '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  _agentColorClass(agent) {
    const a = (agent || '').toLowerCase();
    if (a.includes('cve'))          return 'agent-feed__agent--cve';
    if (a.includes('osint'))        return 'agent-feed__agent--osint';
    if (a.includes('risk'))         return 'agent-feed__agent--risk';
    if (a.includes('report'))       return 'agent-feed__agent--report';
    if (a.includes('orchestrat'))   return 'agent-feed__agent--orchestrator';
    return 'agent-feed__agent--system';
  }

  /**
   * Escape HTML special characters.
   * @param {string} str
   * @returns {string}
   */
  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
}

/* ── Bootstrap ─────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  window.app = new VendorRiskApp();
});
