# -*- coding: utf-8 -*-
import hashlib
import logging
import re

import webcolors

from lncrawl.core.crawler import Crawler
from lncrawl.models.chapter import Chapter
from lncrawl.models.volume import Volume

logger = logging.getLogger(__name__)


memo = {}

_nonbmp = re.compile(r"[\U00010000-\U0010FFFF]")


def _nonbmp_to_entity(match):
    char = match.group()
    assert ord(char) > 0xFFFF
    return f"&#{ord(char)};"


def get_colour_name(hex):
    if hex in memo:
        return memo[hex]

    rgb_triplet = webcolors.hex_to_rgb(hex)
    min_colours = {}
    for key, name in webcolors.CSS3_HEX_TO_NAMES.items():
        r_c, g_c, b_c = webcolors.hex_to_rgb(key)
        rd = (r_c - rgb_triplet[0]) ** 2
        gd = (g_c - rgb_triplet[1]) ** 2
        bd = (b_c - rgb_triplet[2]) ** 2
        min_colours[(rd + gd + bd)] = name

    res = min_colours[min(min_colours.keys())]
    memo[hex] = res
    return res


class WanderingInnCrawler(Crawler):
    base_url = ["https://wanderinginn.com/"]

    def initialize(self) -> None:
        self.novel_url = "https://wanderinginn.com/table-of-contents/"
        self.cleaner.bad_text_regex.update(
            ["Previous Chapter", "Table of Contents", "Next Chapter"]
        )

    def read_novel_info(self):
        logger.debug("Visiting %s", self.novel_url)
        soup = self.get_soup(self.novel_url)

        possible_title = soup.select_one('meta[property="og:site_name"]')
        assert possible_title, "No novel title"
        self.novel_title = possible_title["content"]
        logger.info("Novel title: %s", self.novel_title)

        # possible_novel_cover = soup.select_one('meta[property="og:image"]')
        # if possible_novel_cover:
        #     self.novel_cover = self.absolute_url(possible_novel_cover["content"])
        # logger.info("Novel cover: %s", self.novel_cover)

        self.novel_author = "Pirateaba"
        logger.info("Novel author: %s", self.novel_author)

        # Extract volume-wise chapter entries
        # Stops external links being selected as chapters
        toc = soup.select("div.entry-content>*")

        volume = 0
        chapter = 0

        for el in toc:
            if not el.has_attr("class"):
                continue
            if "book" in el.attrs["class"]:
                volume += 1

                self.volumes.append(
                    Volume(volume, el.text.strip() or ("Volume %d" % volume))
                )

            elif "chapters" in el.attrs["class"] and volume != None:
                for a in el.select('a[href*="/20"]'):
                    chapter += 1
                    url = self.absolute_url(a["href"])
                    self.chapters.append(
                        Chapter(
                            chapter,
                            url,
                            a.text.strip() or ("Chapter %d" % chapter),
                            volume,
                        )
                    )

                    v = self.volumes[-1]
                    v.update(
                        {
                            "start_chapter": chapter
                            if v.start_chapter is None
                            else v.start_chapter,
                            "final_chapter": chapter,
                            "chapter_count": (v.chapter_count or 0) + 1,
                        }
                    )

    def download_chapter_body(self, chapter):
        soup = self.get_soup(chapter["url"])

        body_parts = soup.select_one("div.entry-content")

        for el in body_parts.select("[style]"):
            for part in [x.strip() for x in el["style"].split(";")]:
                if not part.startswith("color:"):
                    continue
                hex = part.split(":")[1].strip()
                nice_colorname = get_colour_name(hex)

                el.insert_before(f"[[{nice_colorname}: ")
                el.insert_after("]]")

        return self.cleaner.extract_contents(body_parts)

    def extract_chapter_images(self, chapter: Chapter) -> None:
        # extract_chapter_images also rewrites the img src= attribute to point
        # to the correct path in the epub archive
        super().extract_chapter_images(chapter)

        # ... so we have to do this here
        # etree.fromstring fails when the (unicode) content contains non-bmp unicode
        # replace any emojis and such with their equivalently-encoded html entity
        chapter.body = _nonbmp.sub(_nonbmp_to_entity, chapter.body)
