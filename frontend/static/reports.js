/* Tabular records go to the user interface; the language model receives report metadata. */
const reportState = {records: new Map(), active: null, page: 0, order: null, descending: false, opener: null};
const reportDialog = document.querySelector('#report-dialog');
const reportText = value => value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
function resetReports() {
  reportState.records.clear(); reportState.active = null;
  if (reportDialog.open) reportDialog.close();
}
function receiveReport(report) {
  if (!report || !report.id || !Array.isArray(report.rows) || !Array.isArray(report.columns)) return;
  if (reportState.records.has(report.id)) return;
  reportState.records.set(report.id, report);
  const card = document.createElement('div'); card.className = 'report-card';
  const title = document.createElement('strong'); title.textContent = report.title || 'Store records';
  const detail = document.createElement('p');
  detail.textContent = `${report.rows.length.toLocaleString()} of ${Number(report.total_matching).toLocaleString()} records · ${report.complete ? 'Complete report' : 'Partial report'}`;
  const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Open report';
  button.onclick = () => {
    reportState.active = report; reportState.page = 0; reportState.order = null; reportState.opener = button;
    document.querySelector('#report-search').value = '';
    document.querySelector('#report-title').textContent = title.textContent;
    document.querySelector('#report-description').textContent = `Store ${report.store_id} · ${report.complete ? 'All matching records' : `${report.rows.length} of ${report.total_matching} matching records`}`;
    renderReport(); reportDialog.showModal(); document.querySelector('#report-search').focus();
  };
  card.append(title, detail, button); document.querySelector('#log').appendChild(card);
}
function reportRows() {
  const report = reportState.active;
  if (!report) return [];
  const query = document.querySelector('#report-search').value.trim().toLocaleLowerCase();
  const rows = report.rows.filter(row => !query || report.columns.some(column => reportText(row[column]).toLocaleLowerCase().includes(query)));
  if (reportState.order) rows.sort((a, b) => {
    const left = a[reportState.order], right = b[reportState.order];
    const comparison = typeof left === 'number' && typeof right === 'number' ? left - right : reportText(left).localeCompare(reportText(right), undefined, {numeric: true});
    return reportState.descending ? -comparison : comparison;
  });
  return rows;
}
function renderReport() {
  const report = reportState.active; if (!report) return;
  const rows = reportRows(), size = 50;
  reportState.page = Math.min(reportState.page, Math.max(0, Math.ceil(rows.length / size) - 1));
  const table = document.querySelector('#report-table'); table.replaceChildren();
  const header = table.createTHead().insertRow();
  for (const column of report.columns) {
    const th = document.createElement('th'); th.scope = 'col';
    const button = document.createElement('button'); button.type = 'button'; button.textContent = column.replaceAll('_', ' ');
    th.setAttribute('aria-sort', reportState.order === column ? (reportState.descending ? 'descending' : 'ascending') : 'none');
    button.onclick = () => { reportState.descending = reportState.order === column ? !reportState.descending : false; reportState.order = column; renderReport(); };
    th.appendChild(button); header.appendChild(th);
  }
  const body = table.createTBody();
  for (const row of rows.slice(reportState.page * size, (reportState.page + 1) * size)) {
    const tr = body.insertRow();
    for (const column of report.columns) {
      const td = tr.insertCell(); td.textContent = readableText(reportText(row[column]));
      if (typeof row[column] === 'number') td.className = 'numeric';
    }
  }
  const first = rows.length ? reportState.page * size + 1 : 0;
  document.querySelector('#report-page').textContent = `${first}–${Math.min((reportState.page + 1) * size, rows.length)} of ${rows.length.toLocaleString()}`;
  document.querySelector('#report-prev').disabled = reportState.page === 0;
  document.querySelector('#report-next').disabled = (reportState.page + 1) * size >= rows.length;
}
function reportCsvCell(value) {
  let text = reportText(value);
  if (/^[\s]*[=+\-@]/.test(text) && typeof value !== 'number') text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}
document.querySelector('#report-search').oninput = () => { reportState.page = 0; renderReport(); };
document.querySelector('#report-prev').onclick = () => { reportState.page--; renderReport(); };
document.querySelector('#report-next').onclick = () => { reportState.page++; renderReport(); };
document.querySelector('#report-close').onclick = () => reportDialog.close();
reportDialog.addEventListener('close', () => { if (reportState.opener?.isConnected) reportState.opener.focus({preventScroll: true}); });
document.querySelector('#report-download').onclick = () => {
  const report = reportState.active; if (!report) return;
  const csv = [report.columns, ...report.rows.map(row => report.columns.map(column => row[column]))].map(row => row.map(reportCsvCell).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff', csv], {type: 'text/csv;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url;
  link.download = `${String(report.resource || 'store').replace(/[^a-z0-9_-]/gi, '')}-${String(report.store_id).replace(/[^a-z0-9_-]/gi, '')}.csv`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
