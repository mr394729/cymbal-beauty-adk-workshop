"""Review ordering and provenance must remain truthful for product comparisons."""
from agents.cymbal_store_ops.tools.domain_tools import get_product_details


def test_product_reviews_are_latest_dated_sample_not_first_source_rows(fake_backend):
    pid = fake_backend.products[0]['product_id']
    fake_backend.reviews = [
        {'review_id': rid, 'product_id': pid, 'created_at': date, 'rating': rating,
         'title': 'Experience', 'body': f'Review {rid}', 'skin_type': 'sensitive'}
        for rid, date, rating in [
            ('old', '2026-01-01T00:00:00+00:00', 5),
            ('new-b', '2026-09-01T00:00:00+00:00', 2),
            ('mid', '2026-08-01T00:00:00+00:00', 3),
            ('new-a', '2026-09-01T00:00:00+00:00', 1),
        ]
    ]
    result = get_product_details(pid)['rows'][0]
    assert [r['review_id'] for r in result['top_reviews']] == ['new-a', 'new-b', 'mid']
    assert result['available_review_count'] == 4
    assert result['review_sample_basis'] == 'latest 3, not a representative sample'
    assert all(r['skin_type'] == 'sensitive' and r['created_at'] for r in result['top_reviews'])


def test_product_without_reviews_has_no_fabricated_review(fake_backend):
    fake_backend.reviews = []
    result = get_product_details(fake_backend.products[0]['product_id'])['rows'][0]
    assert result['top_reviews'] == []
    assert result['available_review_count'] == 0
