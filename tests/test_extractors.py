"""
Tests for the extraction layer.

These parsers are the most fragile part of the package - they consume whatever
shape Instagram's API, GraphQL and embed endpoints happen to return - so the
response shapes are pinned here as fixtures rather than fetched over the network.
"""

import json
import unittest
from unittest import mock

from parth_dl.extractors import BaseExtractor, MediaExtractor, ProfilePictureExtractor
from parth_dl.utils import DownloadError, NetworkError, RateLimitError


def api_video_item():
    """A plain video post, as /api/v1/media/<id>/info/ returns it"""
    return {
        'pk': '3123456789012345678',
        'user': {'username': 'parthmax_'},
        'caption': {'text': 'sunrise over lucknow'},
        'video_duration': 12.5,
        'video_versions': [
            {'url': 'https://cdn/lo.mp4', 'width': 480, 'height': 854},
            {'url': 'https://cdn/hi.mp4', 'width': 720, 'height': 1280},
        ],
        'image_versions2': {'candidates': [{'url': 'https://cdn/thumb.jpg',
                                            'width': 720, 'height': 1280}]},
    }


def api_carousel_item():
    """A carousel mixing one image child and one video child"""
    return {
        'pk': '3123456789012345678',
        'user': {'username': 'parthmax_'},
        'caption': {'text': 'trip dump'},
        'carousel_media': [
            {'image_versions2': {'candidates': [
                {'url': 'https://cdn/1.jpg', 'width': 1080, 'height': 1080}]}},
            {'video_versions': [
                {'url': 'https://cdn/2.mp4', 'width': 720, 'height': 1280}]},
        ],
        'image_versions2': {'candidates': [{'url': 'https://cdn/cover.jpg'}]},
    }


def graphql_media():
    """GraphQL shape - note the null dimensions, which Instagram really does send"""
    return {
        'shortcode': 'ABC123',
        'owner': {'username': 'parthmax_'},
        'is_video': True,
        'video_url': 'https://cdn/v.mp4',
        'display_url': 'https://cdn/poster.jpg',
        'dimensions': {'width': None, 'height': None},
        'edge_media_to_caption': {'edges': [{'node': {'text': 'a caption'}}]},
    }


def graphql_sidecar():
    """GraphQL carousel (edge_sidecar_to_children)"""
    return {
        'shortcode': 'ABC123',
        'owner': {'username': 'parthmax_'},
        'is_video': False,
        'display_url': 'https://cdn/cover.jpg',
        'edge_media_to_caption': {'edges': []},
        'edge_sidecar_to_children': {'edges': [
            {'node': {'display_url': 'https://cdn/a.jpg',
                      'dimensions': {'width': 1080, 'height': 1080}}},
            {'node': {'video_url': 'https://cdn/b.mp4',
                      'display_url': 'https://cdn/b.jpg',
                      'dimensions': {'width': 720, 'height': 1280}}},
        ]},
    }


class ShortcodeTest(unittest.TestCase):

    def setUp(self):
        self.extractor = BaseExtractor()

    def test_round_trip(self):
        # A leading 'A' is index 0, i.e. a leading zero, and cannot survive the
        # round trip - real shortcodes are derived from a numeric id and so
        # never start with one.
        for shortcode in ['C-x_9', 'DhX7yZq1aBc', 'Cxyz123AbCd']:
            media_id = self.extractor._shortcode_to_mediaid(shortcode)
            self.assertEqual(self.extractor._mediaid_to_shortcode(media_id), shortcode)

    def test_media_id_with_user_suffix(self):
        # The API hands back "<media_id>_<user_id>"; only the first half is the code
        self.assertEqual(
            self.extractor._mediaid_to_shortcode('3123456789012345678_1234'),
            self.extractor._mediaid_to_shortcode('3123456789012345678'),
        )

    def test_malformed_shortcode_is_rejected(self):
        # '!' is not in the base64 alphabet - this must not silently mis-convert
        with self.assertRaises(DownloadError):
            self.extractor._shortcode_to_mediaid('AB!123')

    def test_every_http_request_uses_the_shared_rate_limiter(self):
        limiter = mock.Mock()
        extractor = BaseExtractor(rate_limiter=limiter)
        response = mock.Mock()
        response.read.return_value = b'{}'
        response.headers = {}
        extractor.opener.open = mock.Mock(return_value=response)

        extractor._make_request('https://www.instagram.com/p/ABC/')

        limiter.wait_if_needed.assert_called_once_with()

    def test_only_supported_standard_library_encoding_is_advertised(self):
        self.assertEqual(BaseExtractor.BASE_HEADERS['Accept-Encoding'], 'gzip')


class ParseApiItemTest(unittest.TestCase):

    def setUp(self):
        self.extractor = MediaExtractor()

    def test_single_video(self):
        info = self.extractor._parse_media_item(api_video_item())

        self.assertEqual(info['uploader'], 'parthmax_')
        self.assertEqual(info['type'], 'video')
        self.assertEqual(info['title'], 'sunrise over lucknow')
        self.assertEqual(info['caption'], 'sunrise over lucknow')
        self.assertEqual(info['thumbnail'], 'https://cdn/thumb.jpg')

        self.assertEqual(len(info['entries']), 1)
        entry = info['entries'][0]
        self.assertEqual(entry['kind'], 'video')
        self.assertEqual(len(entry['formats']), 2)
        # Video formats from the API carry audio; the downloader relies on this
        self.assertTrue(all(f['has_audio'] for f in entry['formats']))

    def test_mixed_carousel_keeps_every_child(self):
        info = self.extractor._parse_media_item(api_carousel_item())

        self.assertEqual(info['type'], 'carousel')
        self.assertEqual([e['kind'] for e in info['entries']], ['image', 'video'])

    def test_missing_caption_falls_back_to_a_title(self):
        item = api_video_item()
        item['caption'] = None

        info = self.extractor._parse_media_item(item)

        self.assertEqual(info['title'], 'Media by parthmax_')
        self.assertEqual(info['caption'], '')

    def test_long_caption_is_trimmed_in_title_by_default(self):
        item = api_video_item()
        item['caption'] = {'text': 'x' * 150}

        info = self.extractor._parse_media_item(item)

        self.assertEqual(len(info['title']), 100)
        self.assertEqual(len(info['caption']), 150)

    def test_unlimited_caption_length(self):
        item = api_video_item()
        item['caption'] = {'text': 'x' * 150}
        extractor = MediaExtractor(caption_max_length=None)

        info = extractor._parse_media_item(item)

        self.assertEqual(len(info['title']), 150)
        self.assertEqual(info['caption'], 'x' * 150)

    def test_legacy_keys_are_populated(self):
        # Callers written against the pre-entries API still read info['formats']
        info = self.extractor._parse_media_item(api_video_item())

        self.assertEqual(len(info['formats']), 2)
        self.assertEqual(info['images'], [])


class ParseGraphqlTest(unittest.TestCase):

    def setUp(self):
        self.extractor = MediaExtractor()

    def test_video_with_null_dimensions(self):
        info = self.extractor._parse_graphql_media(graphql_media())

        self.assertEqual(info['type'], 'video')
        self.assertEqual(info['id'], 'ABC123')
        entry = info['entries'][0]
        self.assertEqual(entry['kind'], 'video')
        # Nulls must survive parsing - select_format() is what copes with them
        self.assertIsNone(entry['formats'][0]['width'])

    def test_sidecar_becomes_a_carousel(self):
        info = self.extractor._parse_graphql_media(graphql_sidecar())

        self.assertEqual(info['type'], 'carousel')
        self.assertEqual([e['kind'] for e in info['entries']], ['image', 'video'])

    def test_video_cover_is_not_misreported_as_downloadable_media(self):
        media = graphql_media()
        media.pop('video_url')

        info = self.extractor._parse_graphql_media(media)

        self.assertEqual(info['type'], 'video')
        self.assertEqual(info['entries'], [])
        self.assertEqual(info['images'], [])


class PolarisGraphqlTest(unittest.TestCase):

    def setUp(self):
        self.extractor = MediaExtractor()

    @staticmethod
    def product():
        return {
            'pk': '3925150418023071712',
            'code': 'DZ474JEPb_g',
            'media_type': 2,
            'product_type': 'clips',
            'has_audio': True,
            'caption': {'text': 'Anonymous reel'},
            'user': {'username': 'creator'},
            'video_versions': [
                {'type': 101, 'url': 'https://cdn.example/video.mp4'},
                {'type': 102, 'url': 'https://cdn.example/video.mp4'},
            ],
            'image_versions2': {
                'candidates': [{'url': 'https://cdn.example/cover.jpg'}],
            },
        }

    def test_logged_out_query_returns_combined_video(self):
        response = {
            'data': {
                'xig_polaris_media': {
                    'if_not_gated_logged_out': self.product(),
                },
            },
        }
        with mock.patch.object(
            type(self.extractor), 'cookies',
            new_callable=mock.PropertyMock,
            return_value={'csrftoken': 'csrf-token'},
        ), mock.patch.object(
            self.extractor, '_make_request',
            side_effect=[
                '["LSD",[],{"token":"lsd-token"}',
                '{"status":"ok"}',
                json.dumps(response),
            ],
        ) as request:
            info = self.extractor._extract_from_polaris('DZ474JEPb_g')

        self.assertEqual(info['id'], 'DZ474JEPb_g')
        self.assertEqual(info['uploader'], 'creator')
        self.assertEqual(len(info['entries']), 1)
        # Instagram repeats the same progressive URL under multiple type IDs.
        self.assertEqual(len(info['entries'][0]['formats']), 1)
        self.assertTrue(info['entries'][0]['formats'][0]['has_audio'])

        graphql_call = request.call_args_list[2]
        self.assertEqual(
            graphql_call.args[0], 'https://www.instagram.com/api/graphql',
        )
        self.assertEqual(graphql_call.kwargs['headers']['X-FB-LSD'], 'lsd-token')
        self.assertEqual(
            graphql_call.kwargs['data']['doc_id'],
            MediaExtractor.LOGGED_OUT_QUERY_DOC_ID,
        )

    def test_missing_lsd_token_stops_before_graphql(self):
        with mock.patch.object(
            self.extractor, '_make_request', return_value='<html></html>',
        ) as request:
            self.assertIsNone(
                self.extractor._extract_from_polaris('DZ474JEPb_g'),
            )

        request.assert_called_once_with('https://www.instagram.com/')

    def test_gated_response_is_not_treated_as_downloadable(self):
        with mock.patch.object(
            type(self.extractor), 'cookies',
            new_callable=mock.PropertyMock,
            return_value={'csrftoken': 'csrf-token'},
        ), mock.patch.object(
            self.extractor, '_make_request',
            side_effect=[
                '["LSD",[],{"token":"lsd-token"}',
                '{"status":"ok"}',
                '{"data":{"xig_polaris_media":{"if_not_gated_logged_out":null}}}',
            ],
        ):
            self.assertIsNone(
                self.extractor._extract_from_polaris('DZ474JEPb_g'),
            )


class FallbackChainTest(unittest.TestCase):
    """
    extract() must try every endpoint before giving up - Instagram 403s them
    selectively. The chain runs Embed -> GraphQL -> API.
    """

    def setUp(self):
        self.extractor = MediaExtractor()

    def test_graphql_is_used_when_embed_fails(self):
        with mock.patch.object(self.extractor, '_extract_from_embed',
                               side_effect=Exception('403')) as embed, \
             mock.patch.object(self.extractor, '_extract_from_graphql',
                               return_value={'entries': [{'kind': 'video', 'formats': []}]}) as gql:

            info = self.extractor.extract('https://www.instagram.com/reel/Cxyz123AbCd/')

        embed.assert_called_once()
        gql.assert_called_once()
        self.assertTrue(info['entries'])

    def test_api_is_the_last_resort(self):
        with mock.patch.object(self.extractor, '_extract_from_embed', return_value=None), \
             mock.patch.object(self.extractor, '_extract_from_graphql', return_value=None), \
             mock.patch.object(self.extractor, '_extract_from_api',
                               return_value={'entries': [{'kind': 'image', 'formats': []}]}) as api:

            info = self.extractor.extract('https://www.instagram.com/p/Cxyz123AbCd/')

        api.assert_called_once()
        self.assertEqual(info['entries'][0]['kind'], 'image')

    def test_all_methods_failing_raises(self):
        with mock.patch.object(self.extractor, '_extract_from_api', return_value=None), \
             mock.patch.object(self.extractor, '_extract_from_graphql', return_value=None), \
             mock.patch.object(self.extractor, '_extract_from_embed', return_value=None):

            with self.assertRaises(DownloadError):
                self.extractor.extract('https://www.instagram.com/p/Cxyz123AbCd/')

    def test_rate_limit_is_preserved_after_fallbacks_fail(self):
        with mock.patch.object(
            self.extractor, '_extract_from_embed', side_effect=RateLimitError('429'),
        ), mock.patch.object(
            self.extractor, '_extract_from_graphql', return_value=None,
        ), mock.patch.object(
            self.extractor, '_extract_from_api', return_value=None,
        ):
            with self.assertRaises(RateLimitError):
                self.extractor.extract('https://www.instagram.com/p/Cxyz123AbCd/')

    def test_network_error_is_preserved_after_fallbacks_fail(self):
        with mock.patch.object(
            self.extractor, '_extract_from_embed', side_effect=NetworkError('offline'),
        ), mock.patch.object(
            self.extractor, '_extract_from_graphql', return_value=None,
        ), mock.patch.object(
            self.extractor, '_extract_from_api', return_value=None,
        ):
            with self.assertRaises(NetworkError):
                self.extractor.extract('https://www.instagram.com/p/Cxyz123AbCd/')

    def test_a_method_returning_no_entries_is_not_accepted(self):
        # An empty result is a failure, not a successful extraction of nothing
        with mock.patch.object(self.extractor, '_extract_from_embed',
                               return_value={'entries': []}), \
             mock.patch.object(self.extractor, '_extract_from_graphql',
                               return_value={'entries': [{'kind': 'video', 'formats': []}]}):

            info = self.extractor.extract('https://www.instagram.com/reel/Cxyz123AbCd/')

        self.assertTrue(info['entries'])

    def test_non_media_url_is_rejected(self):
        with self.assertRaises(DownloadError):
            self.extractor.extract('https://www.instagram.com/someuser/')


class ProfilePictureTest(unittest.TestCase):

    def setUp(self):
        self.extractor = ProfilePictureExtractor()

    def test_web_extraction_unescapes_the_url(self):
        page = r'{"profile_pic_url_hd":"https://cdn/pic.jpg?a=1&b=2\/x"}'

        with mock.patch.object(self.extractor, '_make_request', return_value=page):
            info = self.extractor.extract('https://www.instagram.com/parthmax_/')

        url = info['entries'][0]['formats'][0]['url']
        self.assertEqual(url, 'https://cdn/pic.jpg?a=1&b=2/x')
        self.assertEqual(info['type'], 'profile_picture')
        self.assertEqual(info['uploader'], 'parthmax_')

    def test_failure_raises(self):
        with mock.patch.object(self.extractor, '_make_request', return_value='no data here'):
            with self.assertRaises(DownloadError):
                self.extractor.extract('https://www.instagram.com/parthmax_/')


if __name__ == '__main__':
    unittest.main()
