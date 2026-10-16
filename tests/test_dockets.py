from appeals.ingest.dockets import assign, dockets_in, heading_dockets


def test_simple_caption():
    page = """STATE OF VERMONT
SUPERIOR COURT                                    ENVIRONMENTAL DIVISION
                                                  Docket No. 128-8-10 Vtec
In re Brandon Plaza Conditional Use Application"""
    assert heading_dockets(page) == ['128-8-10 Vtec']


def test_bracket_column_and_stacked_numbers():
    page = """In re: Appeal of Wesco, Inc         }      Docket Nos. 209-12-97
                                    }                  Vtec
                                    }      and 175-10-01 Vtec"""
    assert heading_dockets(page) == ['209-12-97 Vtec', '175-10-01 Vtec']


def test_stacked_list_in_label_column():
    page = """Vermont Unit                               Docket Nos. 129-9-12 Vtec
                                                       163-11-12 Vtec
                                                        68-5-14 Vtec
Hinesburg Hannaford"""
    assert heading_dockets(page) == ['129-9-12 Vtec', '163-11-12 Vtec', '68-5-14 Vtec']


def test_citation_inside_a_sentence_is_ignored():
    page = """                                             Docket No. 21-1-08 Vtec
The court relied on Appeal of Doyle, Docket No. 100-5-02 Vtec (Vt. Envtl. Ct. 2003), in deciding."""
    assert heading_dockets(page) == ['21-1-08 Vtec']


def test_wrapped_citation_at_line_start_is_ignored():
    page = """                                             Docket No. 21-1-08 Vtec
Applicant cites Appeal of Doyle,
Docket No. 100-5-02 Vtec (Vt. Envtl. Ct., Jan. 21, 2003) for this point."""
    assert heading_dockets(page) == ['21-1-08 Vtec']


def test_new_format_with_ocr_letter_o():
    page = """VERMONT SUPERIOR COURT
Environmental Division                                          Docket No. 22-ENV-OOO3O"""
    assert heading_dockets(page) == ['22-ENV-00030']


def test_supreme_court_numbers_never_make_dockets():
    assert dockets_in('Supreme Court Docket No. 22-AP-00296') == ['22-AP-00296']
    page = """Supreme Court Docket No. 22-AP-00296
                                       Docket No. 21-ENV-00012"""
    assert heading_dockets(page) == ['21-ENV-00012']


def test_listing_fallback_and_flags():
    dockets, flags = assign('A decision with no caption at all.', '113-8-14 Vtec', 2015)
    assert dockets == [('113-8-14 Vtec', 'listing')]
    assert 'no_heading_docket' in flags
    page = '                                    Docket No. 113-8-14 Vtec'
    dockets, flags = assign(page, '114-8-14 Vtec', 2015)
    assert dockets == [('113-8-14 Vtec', 'heading')]
    assert flags == ['typo_like:114-8-14 Vtec~113-8-14 Vtec']


def test_filed_after_posting():
    _, flags = assign('                                  Docket No. 12-3-19 Vtec', '', 2015)
    assert 'filed_after_posting:12-3-19 Vtec' in flags


def test_implausible_docket_years_are_not_dates():
    from appeals.ingest.dockets import filing_period, filing_year
    assert filing_year('12-3-85 Vtec') is None and filing_period('12-3-85 Vtec') is None       # before the court
    assert filing_year('89-ENV-00001') is None                                                 # 2089
    assert filing_period('116-11-18 Vtec') == '2018-11' and filing_period('25-ENV-00113') == '2025'
    dockets, flags = assign('Docket No. 12-3-85 Vtec\n', '', 2001)
    assert 'implausible_year:12-3-85 Vtec' in flags


def test_an_implausible_posting_date_is_dropped_with_a_note():
    from appeals.ingest.listing import parse_page
    markup = ('<article class="views-row"><a href="/media/1">A decision</a>'
              '<time datetime="0022-03-31T12:00:00Z">03/31/0022</time></article>')
    [entry] = parse_page(markup, 'snap', 0)
    assert entry.posted is None and entry.note.startswith('posting date 0022-03-31 dropped: the year 22 is outside 1990')
