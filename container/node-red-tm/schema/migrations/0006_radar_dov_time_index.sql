-- An index on the radar readings' time.
--
-- Without it, every query on radar_dov reads the whole table: each event's radar query, which
-- asks for the few seconds around the event; the newest readings; and a date-range export. With
-- it, each reads only its own stretch of time. Building it reads the whole table once, and it
-- takes about a fifth of the table's size on the card.
--
-- This migration changes no row. It is a file of its own so that a card too full to build the
-- index still gets 0005's columns. The device then records as before without the index; each
-- start of Node-RED tries again, which makes the start longer, and the Status page reports the
-- database schema as behind until the index is built.

CREATE INDEX IF NOT EXISTS index_radar_dov_time ON radar_dov(time);
