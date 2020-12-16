import pyspark.sql as spark

from databand import output, parameter
from dbnd import log_dataframe, log_metric
from dbnd_spark.spark import PySparkInlineTask, spark_task
from targets import Target
from targets.target_config import FileFormat


@spark_task(result=output[spark.DataFrame])
def word_count_inline(text=parameter.csv[spark.DataFrame], counters=output.txt.data):
    # type:  (spark.DataFrame, Target) -> spark.DataFrame
    from operator import add
    from dbnd_spark.spark import get_spark_session

    lines = text.rdd.map(lambda r: r[0])
    counts = (
        lines.flatMap(lambda x: x.split(" ")).map(lambda x: (x, 1)).reduceByKey(add)
    )
    counts.saveAsTextFile(str(counters))
    output = counts.collect()
    for (word, count) in output:
        print("%s: %i" % (word, count))

    counts_df = get_spark_session().createDataFrame(counts)
    log_dataframe("counts_df", counts_df)
    log_metric("test", 1)

    return counts_df


class WordCountSparkInline(PySparkInlineTask):
    text = parameter.csv[spark.DataFrame]
    counters = output.txt.data
    counters_auto_save = output[spark.DataFrame]

    def run(self):
        from operator import add
        from dbnd_spark.spark import get_spark_session

        lines = self.text.rdd.map(lambda r: r[0])
        counts = (
            lines.flatMap(lambda x: x.split(" ")).map(lambda x: (x, 1)).reduceByKey(add)
        )
        counts.saveAsTextFile(str(self.counters))
        output = counts.collect()
        for (word, count) in output:
            print("%s: %i" % (word, count))

        self.counters_auto_save = get_spark_session().createDataFrame(counts)


@spark_task(result=output.save_options(FileFormat.csv, header=True)[spark.DataFrame])
def custom_load_save_options(
    data=parameter.load_options(FileFormat.csv, header=False, sep="\t")[spark.DataFrame]
):
    print(data.show())
    return data
