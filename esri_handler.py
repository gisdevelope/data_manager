# -*- coding: utf-8 -*-
try:
    import ogr
    import osr
except BaseException:
    from osgeo import ogr, osr
import json
import os
from contextlib import contextmanager
from uuid import uuid4

from esridump.dumper import EsriDumper
from geonode.people.models import Profile
from requests.exceptions import ConnectionError

from ags2sld.handlers import Layer as AgsLayer

from .exceptions import EsriException, EsriFeatureLayerException
from .handlers import DataManager, get_connection
from .helpers import urljoin
from .layer_manager import GpkgLayer
from .publishers import ICON_REL_PATH, GeonodePublisher, GeoserverPublisher
from .serializers import EsriSerializer
from .utils import SLUGIFIER, get_new_dir

try:
    from celery.utils.log import get_task_logger as get_logger
except ImportError:
    from cartoview.log_handler import get_logger


logger = get_logger(__name__)


class EsriHandler(EsriDumper):
    def get_esri_serializer(self):
        s = EsriSerializer(self._layer_url)
        return s

    def get_geom_coords(self, geom_dict):
        if "rings" in geom_dict:
            return geom_dict["rings"]
        elif "paths" in geom_dict:
            return geom_dict["paths"] if len(
                geom_dict["paths"]) > 1 else geom_dict["paths"][0]
        else:
            return geom_dict["coordinates"]

    def create_feature(self, layer, featureDict, expected_type, srs=None):
        try:
            geom_dict = featureDict["geometry"]
            if not geom_dict:
                raise EsriFeatureLayerException("No Geometry Information")
            geom_type = geom_dict["type"]
            feature = ogr.Feature(layer.GetLayerDefn())
            coords = self.get_geom_coords(geom_dict)
            f_json = json.dumps({"type": geom_type, "coordinates": coords})
            geom = ogr.CreateGeometryFromJson(f_json)
            if geom and srs:
                geom.Transform(srs)
            if geom and expected_type != geom.GetGeometryType():
                geom = ogr.ForceTo(geom, expected_type)
            if geom and expected_type == geom.GetGeometryType(
            ) and geom.IsValid():
                feature.SetGeometry(geom)
                for prop, val in featureDict["properties"].items():
                    name = str(SLUGIFIER(prop)).encode('utf-8')
                    value = val
                    if value and layer.GetLayerDefn().GetFieldIndex(name) != -1:
                        feature.SetField(name, value)
                layer.CreateFeature(feature)
        except Exception as e:
            logger.error(e)

    def _unique_name(self, name):
        if len(name) > 63:
            name = name[:63]
        if not GpkgLayer.check_geonode_layer(name):
            return str(name)
        suffix = uuid4().__str__().split('-').pop()
        if len(name) < (63 - (len(suffix) + 1)):
            name += "_" + suffix
        else:
            name = name[:((63 - len(suffix)) - 2)] + "_" + suffix

        return self._unique_name(SLUGIFIER(name))

    def get_new_name(self, name):
        name = SLUGIFIER(name.lower())
        return self._unique_name(name)

    @contextmanager
    def create_source_layer(self, source, name, projection, gtype, options):
        layer = source.CreateLayer(
            str(name), srs=projection, geom_type=gtype, options=options)
        yield layer
        layer = None

    def esri_to_postgis(self,
                        overwrite=False,
                        temporary=False,
                        launder=False,
                        name=None,
                        geom_name='geom'):
        gpkg_layer = None
        try:
            es = self.get_esri_serializer()
            if not name:
                name = self.get_new_name(es.get_name())
            feature_iter = iter(self)
            first_feature = next(feature_iter)
            with DataManager.open_source(get_connection(),
                                         is_postgres=True) as source:
                options = [
                    'OVERWRITE={}'.format("YES" if overwrite else 'NO'),
                    'TEMPORARY={}'.format("OFF" if not temporary else "ON"),
                    'LAUNDER={}'.format("YES" if launder else "NO"),
                    'GEOMETRY_NAME={}'.format(
                        geom_name if geom_name else 'geom')
                ]
                gtype = es.get_geometry_type()
                coord_trans = None
                OSR_WGS84_REF = osr.SpatialReference()
                OSR_WGS84_REF.ImportFromEPSG(4326)
                projection = es.get_projection()
                if projection != OSR_WGS84_REF:
                    coord_trans = osr.CoordinateTransformation(
                        OSR_WGS84_REF, projection)
                with self.create_source_layer(source, str(name), projection,
                                              gtype, options) as layer:
                    for field in es.build_fields():
                        layer.CreateField(field)
                    layer.StartTransaction()
                    gpkg_layer = GpkgLayer(layer, source)
                    self.create_feature(layer, first_feature,
                                        gtype, srs=coord_trans)
                    for next_feature in feature_iter:
                        self.create_feature(
                            layer, next_feature, gtype, srs=coord_trans)
                    layer.CommitTransaction()
        except (StopIteration, EsriException, EsriFeatureLayerException,
                ConnectionError) as e:
            logger.debug(e.message)
            if isinstance(e, EsriFeatureLayerException):
                logger.info(e.message)
            if isinstance(e, EsriException):
                layer = None
            logger.error(e.message)
        finally:
            return gpkg_layer

    def publish(self,
                overwrite=False,
                temporary=False,
                launder=False,
                name=None):
        try:
            geonode_layer = None
            user = Profile.objects.filter(is_superuser=True).first()
            layer = self.esri_to_postgis(overwrite, temporary, launder, name)
            if not layer:
                raise Exception("failed to dump layer")
            gs_layername = layer.get_new_name()
            gs_pub = GeoserverPublisher()
            geonode_pub = GeonodePublisher(owner=user)
            published = gs_pub.publish_postgis_layer(
                gs_layername, layername=gs_layername)
            if published:
                agsURL, agsId = self._layer_url.rsplit('/', 1)
                tmp_dir = get_new_dir()
                ags_layer = AgsLayer(
                    agsURL + "/", int(agsId), dump_folder=tmp_dir)
                try:
                    ags_layer.dump_sld_file()
                except Exception as e:
                    logger.error(e.message)
                sld_path = None
                icon_paths = []
                for file in os.listdir(tmp_dir):
                    if file.endswith(".sld"):
                        sld_path = os.path.join(tmp_dir, file)
                icons_dir = os.path.join(tmp_dir, ags_layer.name)
                if os.path.exists(icons_dir):
                    for file in os.listdir(icons_dir):
                        if file.endswith(".png"):
                            icon_paths.append(
                                os.path.join(tmp_dir, ags_layer.name, file))
                        if file.endswith(".svg"):
                            icon_paths.append(
                                os.path.join(tmp_dir, ags_layer.name, file))
                if len(icon_paths) > 0:
                    for icon_path in icon_paths:
                        uploaded = gs_pub.upload_file(
                            open(icon_path),
                            rel_path=urljoin(ICON_REL_PATH, ags_layer.name))
                        if not uploaded:
                            logger.error("Failed To Upload SLD Icon {}".format(
                                icon_path))
                if sld_path:
                    sld_body = None
                    with open(sld_path, 'r') as sld_file:
                        sld_body = sld_file.read()
                    style = gs_pub.create_style(
                        gs_layername, sld_body, overwrite=True)
                    if style:
                        gs_pub.set_default_style(gs_layername, style)

            geonode_layer = geonode_pub.publish(gs_layername)
            if geonode_layer:
                logger.info(geonode_layer.alternate)
                gs_pub.remove_cached(geonode_layer.alternate)

        except Exception as e:
            logger.error(e.message)
        finally:
            return geonode_layer
